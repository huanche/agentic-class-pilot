import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import fs from 'node:fs/promises';
import path from 'node:path';
import { randomUUID, createHash } from 'node:crypto';
import { generateCachedTts, ttsAudioCacheKey } from '@/lib/server/tts-audio-cache';
import type { TTSModelConfig } from '@/lib/audio/types';

function wav() {
  const bytes = Buffer.alloc(16044);
  bytes.write('RIFF');
  bytes.writeUInt32LE(16036, 4);
  bytes.write('WAVEfmt ', 8);
  bytes.writeUInt32LE(16, 16);
  bytes.writeUInt16LE(1, 20);
  bytes.writeUInt16LE(1, 22);
  bytes.writeUInt32LE(8000, 24);
  bytes.writeUInt32LE(16000, 28);
  bytes.writeUInt16LE(2, 32);
  bytes.writeUInt16LE(16, 34);
  bytes.write('data', 36);
  bytes.writeUInt32LE(16000, 40);
  for (let i = 44; i < bytes.length; i += 2) bytes.writeInt16LE(Math.round(Math.sin(i) * 4000), i);
  return { audio: bytes, format: 'wav' };
}
const config: TTSModelConfig = {
  providerId: 'lemonade-tts',
  modelId: 'kokoro-v1',
  voice: 'zf_xiaoyi',
  speed: 1,
  baseUrl: 'http://127.0.0.1:13305/v1',
  providerOptions: { languageType: '中文' },
};
let directory: string;
beforeEach(async () => {
  directory = path.resolve('.runtime', `tts-cache-test-${randomUUID()}`);
  vi.stubEnv('TTS_AUDIO_CACHE_DIR', directory);
  vi.stubEnv('TTS_AUDIO_CACHE_ENABLED', 'true');
  await fs.mkdir(directory, { recursive: true });
});
afterEach(async () => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
  if (!directory.startsWith(path.resolve('.runtime') + path.sep))
    throw new Error('Unsafe test path');
  await fs.rm(directory, { recursive: true, force: true });
});
describe('immutable account-scoped narration cache', () => {
  it('never saves a cancelled synthesis as reusable audio', async () => {
    const abort = new AbortController();
    const generate = vi.fn(
      async (received: TTSModelConfig) =>
        new Promise<ReturnType<typeof wav>>((_resolve, reject) => {
          received.signal?.addEventListener('abort', () => reject(received.signal?.reason), {
            once: true,
          });
        }),
    );
    const first = generateCachedTts(
      { ...config, signal: abort.signal },
      '原讲解',
      { scope: 'a' },
      generate,
    );
    const rejected = expect(first).rejects.toThrow();
    await vi.waitFor(() => expect(generate).toHaveBeenCalledOnce());
    abort.abort();
    await rejected;
    const retry = vi.fn(async () => wav());
    await generateCachedTts(config, '原讲解', { scope: 'a' }, retry);
    expect(retry).toHaveBeenCalledOnce();
  });
  it('reuses identical audio bytes across pages without calling TTS again', async () => {
    const generate = vi.fn(async () => wav());
    const statuses: string[] = [];
    const options = { scope: 'teacher-a', onCache: (value: string) => statuses.push(value) };
    const first = await generateCachedTts(config, '相同讲解', options, generate);
    const second = await generateCachedTts(config, '相同讲解', options, generate);
    expect(second).toEqual(first);
    expect(generate).toHaveBeenCalledOnce();
    expect(statuses).toEqual(['miss', 'hit']);
  });
  it.each([
    { voice: 'zm_yunxi' },
    { modelId: 'different-model' },
    { providerId: 'qwen-tts' },
    { speed: 1.1 },
    { baseUrl: 'https://another.example/v1' },
    { apiKey: 'another-account' },
    { providerOptions: { languageType: 'English' } },
  ])('invalidates the cache when synthesis settings change: %s', async (change) => {
    const generate = vi.fn(async () => wav());
    await generateCachedTts(config, '相同讲解', { scope: 'teacher-a' }, generate);
    await generateCachedTts(
      { ...config, ...change } as TTSModelConfig,
      '相同讲解',
      { scope: 'teacher-a' },
      generate,
    );
    expect(generate).toHaveBeenCalledTimes(2);
  });
  it('keeps other teachers and edited text out of an existing cache entry', async () => {
    const generate = vi.fn(async () => wav());
    await generateCachedTts(config, '原讲解', { scope: 'a' }, generate);
    await generateCachedTts(config, '原讲解', { scope: 'b' }, generate);
    await generateCachedTts(config, '新讲解', { scope: 'a' }, generate);
    expect(generate).toHaveBeenCalledTimes(3);
    const key = ttsAudioCacheKey({ ...config, apiKey: 'secret-test-key' }, '私有文字', 'a');
    expect(key).toMatch(/^[a-f0-9]{64}$/);
  });
  it('rejects a damaged cached file and synthesizes a fresh valid clip', async () => {
    const generate = vi.fn(async () => wav());
    const options = { scope: 'a' };
    await generateCachedTts(config, '原讲解', options, generate);
    const file = path.join(
      directory,
      createHash('sha256').update('a').digest('hex'),
      ttsAudioCacheKey(config, '原讲解', 'a') + '.audio',
    );
    await fs.writeFile(file, 'damaged');
    await generateCachedTts(config, '原讲解', options, generate);
    expect(generate).toHaveBeenCalledTimes(2);
  });
  it('expires old clips and invalidates a replaced model revision', async () => {
    const generate = vi.fn(async () => wav());
    const options = { scope: 'a' };
    await generateCachedTts(config, '原讲解', options, generate);
    const file = path.join(
      directory,
      createHash('sha256').update('a').digest('hex'),
      ttsAudioCacheKey(config, '原讲解', 'a') + '.json',
    );
    const meta = JSON.parse(await fs.readFile(file, 'utf8'));
    meta.createdAt = Date.now() - 8 * 24 * 60 * 60 * 1000;
    await fs.writeFile(file, JSON.stringify(meta));
    await generateCachedTts(config, '原讲解', options, generate);
    vi.stubEnv('TTS_AUDIO_CACHE_VERSION', 'replaced-weights');
    await generateCachedTts(config, '原讲解', options, generate);
    expect(generate).toHaveBeenCalledTimes(3);
  });
  it('still returns real synthesis when the cache directory is unavailable', async () => {
    const blocked = path.join(directory, 'not-a-directory');
    await fs.writeFile(blocked, 'file');
    vi.stubEnv('TTS_AUDIO_CACHE_DIR', blocked);
    const generate = vi.fn(async () => wav());
    await expect(generateCachedTts(config, '原讲解', { scope: 'a' }, generate)).resolves.toEqual(
      wav(),
    );
    expect(generate).toHaveBeenCalledOnce();
  });
  it('evicts older clips toward the configured disk budget', async () => {
    vi.stubEnv('TTS_AUDIO_CACHE_MAX_BYTES', '20000');
    let now = Date.now();
    vi.spyOn(Date, 'now').mockImplementation(() => now);
    const generate = vi.fn(async () => wav());
    await generateCachedTts(config, '旧讲解', { scope: 'a' }, generate);
    now += 61000;
    await generateCachedTts(config, '新讲解', { scope: 'a' }, generate);
    const folder = path.join(directory, createHash('sha256').update('a').digest('hex'));
    const files = await fs.readdir(folder);
    expect(files.filter((f) => f.endsWith('.audio'))).toHaveLength(1);
    expect(files).toContain(ttsAudioCacheKey(config, '新讲解', 'a') + '.audio');
  });
  it('never caches a failed or invalid provider response', async () => {
    const generate = vi
      .fn()
      .mockRejectedValueOnce(new Error('quota'))
      .mockResolvedValueOnce({ audio: new Uint8Array([1]), format: 'wav' })
      .mockResolvedValue(wav());
    await expect(generateCachedTts(config, '原讲解', { scope: 'a' }, generate)).rejects.toThrow(
      'quota',
    );
    await generateCachedTts(config, '原讲解', { scope: 'a' }, generate);
    await generateCachedTts(config, '原讲解', { scope: 'a' }, generate);
    expect(generate).toHaveBeenCalledTimes(3);
  });
  it('coalesces duplicate requests without letting one teacher action cancel another waiter', async () => {
    let finish!: () => void;
    const ready = new Promise<void>((resolve) => {
      finish = resolve;
    });
    const generate = vi.fn(async (received: TTSModelConfig) => {
      await ready;
      received.signal?.throwIfAborted();
      return wav();
    });
    const abort = new AbortController();
    const first = generateCachedTts(
      { ...config, signal: abort.signal },
      '原讲解',
      { scope: 'a' },
      generate,
    );
    const rejected = expect(first).rejects.toThrow();
    await vi.waitFor(() => expect(generate).toHaveBeenCalledOnce());
    const statuses: string[] = [];
    const second = generateCachedTts(
      config,
      '原讲解',
      { scope: 'a', onCache: (status) => statuses.push(status) },
      generate,
    );
    await vi.waitFor(() => expect(statuses).toEqual(['shared']));
    abort.abort();
    await rejected;
    finish();
    await expect(second).resolves.toMatchObject({ format: 'wav' });
    expect(generate).toHaveBeenCalledOnce();
  });
  it('can bypass caching for a cold serial baseline', async () => {
    const generate = vi.fn(async () => wav());
    await generateCachedTts(config, '原讲解', { scope: 'a', enabled: false }, generate);
    await generateCachedTts(config, '原讲解', { scope: 'a', enabled: false }, generate);
    expect(generate).toHaveBeenCalledTimes(2);
  });
});
