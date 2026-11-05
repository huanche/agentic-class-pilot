import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { promises as fs } from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import type { PersistedClassroomData } from '@/lib/server/classroom-storage';
import { parseByteRange } from '@/lib/server/http-range';
import { renderGrantAllows, signRenderGrant, verifyRenderGrant } from '@/lib/classroom-video/grant';

const mocks = vi.hoisted(() => ({ classroom: null as PersistedClassroomData | null }));
vi.mock('@/lib/server/course-space-database', () => ({
  readClassroomFromDatabase: async () => mocks.classroom,
  isCourseDatabaseConfigured: () => true,
}));
let temp: string;
beforeEach(async () => {
  temp = await fs.mkdtemp(path.join(os.tmpdir(), 'video-tests-'));
  vi.stubEnv('CLASSROOMS_DATA_DIR', path.join(temp, 'classrooms'));
  vi.stubEnv('CLASSROOM_VIDEOS_DIR', path.join(temp, 'videos'));
  vi.stubEnv('CLASSROOM_VIDEO_WORKER_URL', 'http://worker');
  vi.stubEnv('CLASSROOM_VIDEO_SECRET', 's'.repeat(32));
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response('{}', { status: 202 })),
  );
  vi.resetModules();
});
afterEach(async () => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  await fs.rm(temp, { recursive: true, force: true });
});

function lesson() {
  mocks.classroom = {
    id: 'lesson',
    stage: { id: 'lesson', name: 'Lesson' },
    scenes: [1, 2].map((n) => ({
      id: `s${n}`,
      stageId: 'lesson',
      title: `Page ${n}`,
      order: n,
      type: 'slide',
      content: { type: 'slide', canvas: { id: `canvas${n}`, elements: [] } },
      actions: [{ id: `speech${n}`, type: 'speech', text: `Text ${n}`, audioId: `pool${n}` }],
    })),
    createdAt: 'now',
  } as unknown as PersistedClassroomData;
  return mocks.classroom;
}
async function audio() {
  await fs.mkdir(path.join(temp, 'classrooms/lesson/audio'), { recursive: true });
  for (const n of [1, 2])
    await fs.writeFile(
      path.join(temp, `classrooms/lesson/audio/tts_s${n}_speech${n}.wav`),
      Buffer.from(`audio-${n}`),
    );
}
describe('teacher video snapshots', () => {
  it('reports loading, recording and encoding without allowing publication before every clip is ready', async () => {
    lesson();
    await audio();
    const { prepareClassroomVideo, videoPath, videoStatus, preparedVideoForPublication } =
      await import('@/lib/server/classroom-video');
    const plan = await prepareClassroomVideo('lesson', 'owner', 'https://example.com');
    await fs.mkdir(videoPath('lesson', 'jobs'), { recursive: true });
    await fs.mkdir(videoPath('lesson', 'clips'), { recursive: true });
    for (const phase of ['loading', 'recording', 'encoding']) {
      await fs.writeFile(
        videoPath('lesson', 'jobs', `${plan.version}.json`),
        JSON.stringify({ state: 'rendering', currentSceneId: 's1', phase }),
      );
      expect(await videoStatus(plan)).toMatchObject({
        state: 'rendering',
        phase,
        currentSceneId: 's1',
        completed: 0,
      });
      await expect(preparedVideoForPublication('lesson')).rejects.toThrow('视频尚未转换完成');
    }
    for (const clip of plan.clips)
      await fs.writeFile(
        videoPath('lesson', 'clips', `${clip.key}.mp4`),
        'validated-worker-output',
      );
    expect(await videoStatus(plan)).toMatchObject({ state: 'ready', completed: 2 });
    expect((await videoStatus(plan)).phase).toBeUndefined();
    expect(await preparedVideoForPublication('lesson')).toBe(plan.version);
  });
  it('reuses unchanged pages, invalidates only a changed page or changed audio bytes', async () => {
    const c = lesson();
    await audio();
    const { prepareClassroomVideo } = await import('@/lib/server/classroom-video');
    const first = await prepareClassroomVideo('lesson', 'owner', 'https://example.com');
    c.scenes[0].actions![0] = { ...c.scenes[0].actions![0], audioId: 'different-pool-id' } as never;
    c.scenes[0].updatedAt = Date.now();
    const same = await prepareClassroomVideo('lesson', 'owner', 'https://example.com');
    expect(same.version).toBe(first.version);
    c.scenes[1].title = 'New title';
    c.scenes[1].content = {
      ...c.scenes[1].content,
      canvas: { id: 'changed', elements: [] },
    } as never;
    const edited = await prepareClassroomVideo('lesson', 'owner', 'https://example.com');
    expect(edited.version).not.toBe(first.version);
    expect(edited.clips[0].key).toBe(first.clips[0].key);
    expect(edited.clips[1].key).not.toBe(first.clips[1].key);
    await fs.writeFile(path.join(temp, 'classrooms/lesson/audio/tts_s1_speech1.wav'), 'new-audio');
    const voiced = await prepareClassroomVideo('lesson', 'owner', 'https://example.com');
    expect(voiced.clips[0].key).not.toBe(first.clips[0].key);
    expect(voiced.clips[1].key).toBe(edited.clips[1].key);
  });
  it('rejects missing or invalidated narration instead of making a silent video', async () => {
    const c = lesson();
    const { prepareClassroomVideo } = await import('@/lib/server/classroom-video');
    await expect(prepareClassroomVideo('lesson', 'owner', 'https://example.com')).rejects.toThrow(
      '缺少配音',
    );
    await audio();
    (c.scenes[0].actions![0] as { audioInvalidated?: boolean }).audioInvalidated = true;
    await expect(prepareClassroomVideo('lesson', 'owner', 'https://example.com')).rejects.toThrow(
      '讲稿已修改',
    );
  });
  it('retains ready page files when retrying and never changes the published pointer on prepare', async () => {
    lesson();
    await audio();
    const { prepareClassroomVideo, videoPath, videoStatus, videoPointer } =
      await import('@/lib/server/classroom-video');
    const p = await prepareClassroomVideo('lesson', 'owner', 'https://example.com');
    await fs.mkdir(videoPath('lesson', 'clips'), { recursive: true });
    await fs.writeFile(videoPath('lesson', 'clips', `${p.clips[0].key}.mp4`), 'completed');
    expect((await videoStatus(p)).completed).toBe(1);
    const retry = await prepareClassroomVideo('lesson', 'owner', 'https://example.com');
    expect(retry.version).toBe(p.version);
    expect(await fs.readFile(videoPath('lesson', 'clips', `${p.clips[0].key}.mp4`), 'utf8')).toBe(
      'completed',
    );
    expect(await videoPointer('lesson', 'published')).toBeNull();
    await fs.mkdir(videoPath('lesson', 'jobs'), { recursive: true });
    await fs.writeFile(
      videoPath('lesson', 'jobs', `${p.version}.json`),
      JSON.stringify({ state: 'ready' }),
    );
    expect((await videoStatus(p)).state).toBe('failed');
  });
  it('ignores layout measurement drift for native PPTX but invalidates a real canvas edit', async () => {
    const c = lesson();
    await audio();
    c.stage.nativePptx = {
      version: 1,
      renderRevision: 2,
      sha256: 'source',
      sourceSha256: 'source',
      pages: { o1: 5, o2: 6 },
      compatibility: { converted: 0, unresolved: 0 },
    };
    c.scenes[0].outlineId = 'o1';
    c.scenes[1].outlineId = 'o2';
    const { prepareClassroomVideo } = await import('@/lib/server/classroom-video');
    const p = await prepareClassroomVideo('lesson', 'owner', 'https://example.com');
    c.scenes[0].content = { type: 'slide', canvas: { id: 'measured', elements: [] } } as never;
    const measured = await prepareClassroomVideo('lesson', 'owner', 'https://example.com');
    expect(measured.version).toBe(p.version);
    c.scenes[0].nativePptxEdited = true;
    const edited = await prepareClassroomVideo('lesson', 'owner', 'https://example.com');
    expect(edited.clips[0].key).not.toBe(p.clips[0].key);
    expect(edited.clips[1].key).toBe(p.clips[1].key);
  });
  it('keeps the approved video fixed when a later teacher edit creates a new draft', async () => {
    const c = lesson();
    await audio();
    const {
      prepareClassroomVideo,
      videoPath,
      videoPointer,
      preparedVideoForPublication,
      pinPublishedVideo,
    } = await import('@/lib/server/classroom-video');
    const plan = await prepareClassroomVideo('lesson', 'owner', 'https://example.com');
    await fs.mkdir(videoPath('lesson', 'clips'), { recursive: true });
    for (const clip of plan.clips)
      await fs.writeFile(
        videoPath('lesson', 'clips', `${clip.key}.mp4`),
        'validated-worker-output',
      );
    expect(await preparedVideoForPublication('lesson')).toBe(plan.version);
    await pinPublishedVideo('lesson', plan.version);
    c.scenes[0].content = { type: 'slide', canvas: { id: 'edited', elements: [] } } as never;
    await expect(preparedVideoForPublication('lesson')).rejects.toThrow('课件已修改');
    expect((await videoPointer('lesson', 'published'))?.version).toBe(plan.version);
    expect((await videoPointer('lesson', 'draft'))?.version).not.toBe(plan.version);
  });
});
it('scopes render grants to one immutable read snapshot; rejects expiry, tampering, writes and other courses', async () => {
  const claims = { id: 'lesson', version: 'a'.repeat(64), exp: Date.now() + 60_000 },
    secret = 'secret';
  const token = await signRenderGrant(claims, secret);
  expect(await verifyRenderGrant(token, secret)).toEqual(claims);
  expect(await verifyRenderGrant(token + 'x', secret)).toBeNull();
  expect(await verifyRenderGrant(token, secret, claims.exp + 1)).toBeNull();
  const url = new URL(`https://example.com/api/classroom?id=lesson&videoCapture=${claims.version}`);
  expect(renderGrantAllows(claims, url, 'GET')).toBe(true);
  expect(renderGrantAllows(claims, url, 'POST')).toBe(false);
  url.searchParams.set('id', 'other');
  expect(renderGrantAllows(claims, url, 'GET')).toBe(false);
  expect(
    renderGrantAllows(claims, new URL('https://example.com/api/classroom?id=lesson'), 'GET'),
  ).toBe(false);
});
it('serves seek byte ranges and rejects invalid or multipart ranges', () => {
  expect(parseByteRange('bytes=100-', 1000)).toEqual({ start: 100, end: 999 });
  expect(parseByteRange('bytes=-100', 1000)).toEqual({ start: 900, end: 999 });
  expect(parseByteRange('bytes=0-9999', 1000)).toEqual({ start: 0, end: 999 });
  for (const value of ['bytes=1000-', 'bytes=10-5', 'bytes=0-1,4-6', 'bytes=-0'])
    expect(parseByteRange(value, 1000)).toBeNull();
});
it('uses existing clip timing for captions without rerendering and tolerates missing or broken optional metadata', async () => {
  lesson();
  await audio();
  const { prepareClassroomVideo, readClipCaptions, videoPath } =
    await import('@/lib/server/classroom-video');
  const plan = await prepareClassroomVideo('lesson', 'teacher', 'https://example.com');
  const clip = plan.clips[0];
  expect(await readClipCaptions(plan, clip)).toEqual([]);
  await fs.mkdir(videoPath('lesson', 'clips'), { recursive: true });
  const meta = videoPath('lesson', 'clips', `${clip.key}.mp4.json`);
  await fs.writeFile(
    meta,
    JSON.stringify({ duration: 10, speech: [{ actionId: 'speech1', offset: 1.25, duration: 3 }] }),
  );
  expect(await readClipCaptions(plan, clip)).toEqual([{ start: 1.25, end: 4.25, text: 'Text 1' }]);
  await fs.writeFile(meta, 'broken JSON');
  expect(await readClipCaptions(plan, clip)).toEqual([]);
});
