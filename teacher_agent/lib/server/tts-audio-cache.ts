import { createHash, randomUUID } from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import type { TTSModelConfig } from '@/lib/audio/types';
import type { TTSGenerationResult } from '@/lib/audio/tts-providers';
import { measureAudioDuration } from '@/lib/audio/audio-duration';
import { CLASSROOMS_DIR } from './classroom-storage';

export type AudioCacheStatus = 'hit' | 'miss' | 'shared' | 'bypass';
type Entry = {
  controller: AbortController;
  promise: Promise<TTSGenerationResult>;
  users: number;
  settled: boolean;
};
const root = globalThis as typeof globalThis & {
  __ttsAudioCachePending?: Map<string, Entry>;
  __ttsAudioCachePrune?: Map<string, number>;
};
const pending = (root.__ttsAudioCachePending ??= new Map());
const pruning = (root.__ttsAudioCachePrune ??= new Map());
const hash = (value: string | Uint8Array) => createHash('sha256').update(value).digest('hex');
const TTL = 7 * 24 * 60 * 60 * 1000;

function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === 'object')
    return Object.fromEntries(
      Object.entries(value)
        .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
        .map(([k, v]) => [k, canonical(v)]),
    );
  return value;
}

/** Only irreversible hashes reach filenames/metadata. Cache boundaries include the account. */
export function ttsAudioCacheKey(config: TTSModelConfig, text: string, scope: string) {
  const { signal: _signal, apiKey, ...parameters } = config;
  return hash(
    JSON.stringify(
      canonical({
        version: 1,
        modelRevision: process.env.TTS_AUDIO_CACHE_VERSION || '1',
        scope,
        parameters,
        credential: hash(apiKey || ''),
        text,
      }),
    ),
  );
}

async function read(file: string): Promise<TTSGenerationResult | null> {
  try {
    const meta = JSON.parse(await fs.readFile(`${file}.json`, 'utf8'));
    if (
      meta.version !== 1 ||
      !Number.isFinite(meta.createdAt) ||
      Date.now() - meta.createdAt > TTL ||
      !/^(wav|mp3|ogg|aac|pcm)$/.test(meta.format)
    )
      return null;
    const bytes = await fs.readFile(`${file}.audio`);
    if (bytes.length !== meta.bytes || hash(bytes) !== meta.sha256) return null;
    if (!(measureAudioDuration(bytes, meta.format)! > 0)) return null;
    return { audio: bytes, format: meta.format };
  } catch {
    return null;
  } // An unavailable cache must never prevent real synthesis.
}

async function prune(directory: string) {
  const now = Date.now();
  if (now - (pruning.get(directory) || 0) < 60000) return;
  pruning.set(directory, now);
  const configured = Number(process.env.TTS_AUDIO_CACHE_MAX_BYTES);
  const maximum = Number.isFinite(configured) && configured > 0 ? configured : 256 * 1024 * 1024;
  const entries: Array<{ file: string; bytes: number; time: number }> = [];
  for (const scope of await fs.readdir(directory).catch(() => [])) {
    if (!/^[a-f0-9]{64}$/.test(scope)) continue;
    const folder = path.join(directory, scope);
    for (const name of await fs.readdir(folder).catch(() => [])) {
      if (!/^[a-f0-9]{64}\.audio$/.test(name)) continue;
      const file = path.join(folder, name.slice(0, -6));
      const stat = await fs.stat(`${file}.audio`).catch(() => null);
      if (stat) entries.push({ file, bytes: stat.size, time: stat.mtimeMs });
    }
  }
  let total = entries.reduce((sum, e) => sum + e.bytes, 0);
  for (const entry of entries.sort((a, b) => a.time - b.time)) {
    if (total <= maximum && now - entry.time <= TTL) break;
    if (pending.has(entry.file)) continue;
    await fs.unlink(`${entry.file}.json`).catch(() => undefined);
    await fs.unlink(`${entry.file}.audio`).catch(() => undefined);
    total -= entry.bytes;
  }
}

async function write(file: string, directory: string, result: TTSGenerationResult) {
  // Only decodable audio is reusable. Invalid/provider-error payloads are never cached.
  if (!(measureAudioDuration(result.audio, result.format)! > 0)) return;
  const temporary = `${file}.${randomUUID()}.tmp`;
  try {
    await fs.mkdir(path.dirname(file), { recursive: true });
    await fs.writeFile(temporary, result.audio);
    await fs.rename(temporary, `${file}.audio`);
    await fs.writeFile(
      `${temporary}.json`,
      JSON.stringify({
        version: 1,
        format: result.format,
        bytes: result.audio.length,
        sha256: hash(result.audio),
        createdAt: Date.now(),
      }),
    );
    await fs.rename(`${temporary}.json`, `${file}.json`);
    await prune(directory);
  } finally {
    await fs.unlink(temporary).catch(() => undefined);
    await fs.unlink(`${temporary}.json`).catch(() => undefined);
  }
}

/** Independent waiters can cancel; synthesis stops only when every waiter has left. */
async function subscribe(entry: Entry, signal?: AbortSignal): Promise<TTSGenerationResult> {
  signal?.throwIfAborted();
  entry.users++;
  try {
    return await new Promise((resolve, reject) => {
      const abort = () => reject(signal?.reason ?? new DOMException('Cancelled', 'AbortError'));
      signal?.addEventListener('abort', abort, { once: true });
      entry.promise
        .then(resolve, reject)
        .finally(() => signal?.removeEventListener('abort', abort));
      if (signal?.aborted) abort();
    });
  } finally {
    entry.users--;
    if (!entry.users && !entry.settled) entry.controller.abort();
  }
}

export async function generateCachedTts(
  config: TTSModelConfig,
  text: string,
  options: { scope: string; enabled?: boolean; onCache?: (status: AudioCacheStatus) => void },
  generate: (config: TTSModelConfig, text: string) => Promise<TTSGenerationResult>,
): Promise<TTSGenerationResult> {
  config.signal?.throwIfAborted();
  if (options.enabled === false || process.env.TTS_AUDIO_CACHE_ENABLED === 'false') {
    options.onCache?.('bypass');
    return generate(config, text);
  }
  const directory =
    process.env.TTS_AUDIO_CACHE_DIR || path.join(path.dirname(CLASSROOMS_DIR), 'tts-audio-cache');
  const file = path.join(
    directory,
    hash(options.scope),
    ttsAudioCacheKey(config, text, options.scope),
  );
  const cached = await read(file);
  config.signal?.throwIfAborted();
  if (cached) {
    options.onCache?.('hit');
    return cached;
  }
  let entry = pending.get(file);
  if (entry?.controller.signal.aborted) entry = undefined;
  if (entry) options.onCache?.('shared');
  else {
    options.onCache?.('miss');
    const controller = new AbortController();
    const created: Entry = { controller, users: 0, settled: false, promise: null! };
    created.promise = Promise.resolve()
      .then(async () => {
        const result = await generate({ ...config, signal: controller.signal }, text);
        controller.signal.throwIfAborted();
        await write(file, directory, result).catch(() => undefined);
        return result;
      })
      .finally(() => {
        created.settled = true;
        if (pending.get(file) === created) pending.delete(file);
      });
    // The first caller can cancel before subscribing; never leave a rejected producer unobserved.
    void created.promise.catch(() => undefined);
    pending.set(file, created);
    entry = created;
  }
  return subscribe(entry, config.signal);
}
