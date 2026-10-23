import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import fs from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';
import type { Scene } from '@/lib/types/stage';
import { applyNarrationRevisions } from '@/lib/generation/narration-budget';

const fixture = vi.hoisted(() => ({
  generate: vi.fn(),
  folder: `${process.cwd()}/.runtime/narration-reuse-tests`,
}));
vi.mock('@/lib/server/classroom-storage', () => ({
  CLASSROOMS_DIR: `${fixture.folder}/classrooms`,
}));
vi.mock('@/lib/audio/tts-providers', () => ({ generateTTS: fixture.generate }));
vi.mock('@/lib/server/provider-config', () => ({
  getServerImageProviders: () => ({}),
  getServerVideoProviders: () => ({}),
  getServerTTSProviders: () => ({ 'lemonade-tts': { models: ['kokoro-v1'] } }),
  isServerTTSProviderDisabled: () => false,
  resolveTTSApiKey: () => '',
  resolveTTSBaseUrl: () => 'http://127.0.0.1:13305/v1',
  resolveTTSVoice: () => 'zf_xiaoyi',
  resolveTTSModel: (_provider: string, model?: string) => model,
  resolveImageApiKey: () => '',
  resolveImageBaseUrl: () => '',
  resolveVideoApiKey: () => '',
  resolveVideoBaseUrl: () => '',
}));
import {
  generateTTSForClassroom,
  finalizeClassroomTtsAudio,
  removeClassroomTtsAudio,
} from '@/lib/server/classroom-media-generation';

function wav(text: string) {
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
  const offset = text.length % 17;
  for (let i = 44; i < bytes.length; i += 2)
    bytes.writeInt16LE(Math.round(Math.sin(i + offset) * 4000), i);
  return { audio: bytes, format: 'wav' };
}
beforeEach(() => {
  fixture.generate.mockReset().mockImplementation(async (_config, text) => wav(text));
  vi.stubEnv('TTS_AUDIO_CACHE_ENABLED', 'true');
  vi.stubEnv('TTS_AUDIO_CACHE_DIR', `${fixture.folder}/cache`);
});
afterEach(async () => {
  vi.unstubAllEnvs();
  const folder = path.resolve(fixture.folder);
  if (!folder.startsWith(path.resolve('.runtime') + path.sep)) throw new Error('Unsafe test path');
  await fs.rm(folder, { recursive: true, force: true });
});

it('synthesizes only changed text and keeps checkpoint audio readable after candidate rollback', async () => {
  const original = {
    id: 'page',
    stageId: 'class',
    type: 'slide',
    order: 1,
    title: '测试',
    content: { type: 'slide', canvas: { elements: [] } },
    actions: [
      { id: 'a', type: 'speech', text: '第一段完整讲解。' },
      { id: 'b', type: 'speech', text: '第二段完整讲解。' },
      { id: 'c', type: 'speech', text: '第三段完整讲解。' },
    ],
  } as unknown as Scene;
  const options = { isolateAudio: true, failFast: true, cacheScope: 'same-owner' };
  await generateTTSForClassroom([original], 'class', 'http://localhost', undefined, options);
  await finalizeClassroomTtsAudio(original, 'class', 'http://localhost');
  const fileFor = (id: string) => path.join(fixture.folder, 'classrooms/class/audio', `${id}.wav`);
  const hash = (bytes: Buffer) => createHash('sha256').update(bytes).digest('hex');
  const originalFiles = await Promise.all(
    original
      .actions!.filter((a) => a.type === 'speech')
      .map(async (a) => ({
        id: a.audioId!,
        hash: hash(await fs.readFile(fileFor(a.audioId!))),
      })),
  );
  const candidate: Scene = {
    ...original,
    actions: applyNarrationRevisions(
      original.actions!,
      JSON.stringify({ revisions: [{ speechId: 'b', text: '第二段扩展了原有知识点和案例。' }] }),
      ['b'],
    ),
  };
  const cache: string[] = [];
  await generateTTSForClassroom([candidate], 'class', 'http://localhost', undefined, {
    ...options,
    onAudioCache: (value) => cache.push(value),
  });
  expect(cache).toEqual(['hit', 'miss', 'hit']);
  expect(fixture.generate).toHaveBeenCalledTimes(4);
  await finalizeClassroomTtsAudio(candidate, 'class', 'http://localhost');
  for (const index of [0, 2]) {
    const speech = candidate.actions![index];
    expect(speech.type).toBe('speech');
    if (speech.type === 'speech')
      expect(hash(await fs.readFile(fileFor(speech.audioId!)))).toBe(originalFiles[index].hash);
  }
  await removeClassroomTtsAudio(candidate, 'class'); // A failed final checkpoint cleans only the candidate.
  for (const originalFile of originalFiles)
    expect(hash(await fs.readFile(fileFor(originalFile.id)))).toBe(originalFile.hash);
});
