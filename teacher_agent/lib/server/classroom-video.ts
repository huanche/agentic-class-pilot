import { createHash } from 'node:crypto';
import { promises as fs } from 'node:fs';
import path from 'node:path';
import type {
  ClassroomVideoPlan,
  ClassroomVideoStatus,
  VideoClipPlan,
} from '@/lib/classroom-video/types';
import { signRenderGrant } from '@/lib/classroom-video/grant';
import {
  CLASSROOMS_DIR,
  readClassroom,
  writeJsonFileAtomic,
  isValidClassroomId,
} from './classroom-storage';
import { internalPlatformHeaders } from './platform-auth';
import { nativePptxPage } from '@/lib/onlyoffice/native-player';
import { captionsForClip, type ClipTiming } from '@/lib/classroom-video/captions';

export const CLASSROOM_VIDEOS_DIR = path.resolve(
  process.env.CLASSROOM_VIDEOS_DIR || path.join(process.cwd(), 'data/classroom-videos'),
);
export const videoEnabled = () => Boolean(process.env.CLASSROOM_VIDEO_WORKER_URL);
export const videoSecret = () =>
  process.env.CLASSROOM_VIDEO_SECRET || process.env.PLATFORM_SERVICE_KEY || '';
export const digestVideo = (data: string | Buffer) =>
  createHash('sha256').update(data).digest('hex');
export function canonicalVideo(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalVideo).join(',')}]`;
  if (value && typeof value === 'object')
    return `{${Object.entries(value)
      .filter(([, v]) => v !== undefined)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([k, v]) => `${JSON.stringify(k)}:${canonicalVideo(v)}`)
      .join(',')}}`;
  return JSON.stringify(value) ?? 'null';
}
export function videoPath(id: string, ...segments: string[]) {
  if (
    !isValidClassroomId(id) ||
    id.length > 100 ||
    segments.some((s) => !/^[A-Za-z0-9_.-]+$/.test(s) || s.includes('..'))
  )
    throw new Error('Invalid video path');
  return path.join(CLASSROOM_VIDEOS_DIR, id, ...segments);
}
async function readJson<T>(file: string): Promise<T | null> {
  try {
    return JSON.parse(await fs.readFile(file, 'utf8'));
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === 'ENOENT') return null;
    throw e;
  }
}
export async function readVideoPlan(id: string, version: string) {
  if (!/^[a-f0-9]{64}$/.test(version)) throw new Error('Invalid video version');
  return readJson<ClassroomVideoPlan>(videoPath(id, 'versions', `${version}.json`));
}
export async function videoPointer(id: string, kind: 'draft' | 'published') {
  return readJson<{ version: string }>(videoPath(id, `${kind}.json`));
}
export async function readClipCaptions(plan: ClassroomVideoPlan, clip: VideoClipPlan) {
  const scene = plan.scenes.find((s) => s.id === clip.sceneId);
  if (!scene || !/^[a-f0-9]{64}$/.test(clip.key)) return [];
  try {
    const timing = await readJson<ClipTiming>(videoPath(plan.id, 'clips', `${clip.key}.mp4.json`));
    return timing ? captionsForClip(scene, timing) : [];
  } catch {
    // Optional caption metadata must not make an otherwise valid MP4 unplayable.
    return [];
  }
}
export async function videoStatus(plan: ClassroomVideoPlan): Promise<ClassroomVideoStatus> {
  const saved = await readJson<ClassroomVideoStatus>(
    videoPath(plan.id, 'jobs', `${plan.version}.json`),
  );
  let completed = 0;
  for (const clip of plan.clips) {
    if ((await fs.stat(videoPath(plan.id, 'clips', `${clip.key}.mp4`)).catch(() => null))?.size)
      completed++;
  }
  const ready = completed === plan.clips.length;
  const missing = !ready && saved?.state === 'ready';
  return {
    version: plan.version,
    state: ready ? 'ready' : missing ? 'failed' : saved?.state || 'queued',
    completed,
    total: plan.clips.length,
    updatedAt: saved?.updatedAt || plan.createdAt,
    ...(missing
      ? { error: '视频片段缺失，请重试未完成视频' }
      : !ready && saved?.error
        ? { error: saved.error }
        : {}),
    currentSceneId: saved?.currentSceneId,
    phase: !ready && saved?.state === 'rendering' ? saved.phase : undefined,
  };
}
const preparing = new Map<string, Promise<ClassroomVideoPlan>>();
export async function prepareClassroomVideo(id: string, ownerId: string, origin: string) {
  const active = preparing.get(id);
  // Serialize snapshot creation; a later request must still observe later edits.
  if (active) {
    await active.catch(() => {});
    return prepareClassroomVideo(id, ownerId, origin);
  }
  const promise = prepare(id, ownerId, origin);
  preparing.set(id, promise);
  try {
    return await promise;
  } finally {
    if (preparing.get(id) === promise) preparing.delete(id);
  }
}
async function prepare(id: string, ownerId: string, origin: string): Promise<ClassroomVideoPlan> {
  if (!videoEnabled() || !videoSecret()) throw new Error('视频转换服务尚未启用');
  const classroom = await readClassroom(id);
  if (!classroom?.scenes.length) throw new Error('课件尚未生成');
  if (classroom.stage.generationPlan && !classroom.stage.generationPlan.complete)
    throw new Error('请先完成课件生成');
  const scenes = [...classroom.scenes].sort((a, b) => a.order - b.order);
  const clips: VideoClipPlan[] = [];
  for (const scene of scenes.filter((s) => s.type === 'slide')) {
    const audio: VideoClipPlan['audio'] = {};
    for (const action of scene.actions || []) {
      if (action.type !== 'speech') continue;
      if (!/^[A-Za-z0-9_-]+$/.test(action.id) || action.audioInvalidated)
        throw new Error(`“${scene.title}”的讲稿已修改，请先完成配音`);
      let bytes: Buffer | undefined,
        extension = '';
      for (const ext of ['wav', 'mp3', 'ogg', 'aac']) {
        const file = path.join(
          CLASSROOMS_DIR,
          id,
          'audio',
          `tts_s${scene.order}_${action.id}.${ext}`,
        );
        try {
          bytes = await fs.readFile(file);
          extension = ext;
          break;
        } catch (e) {
          if ((e as NodeJS.ErrnoException).code !== 'ENOENT') throw e;
        }
      }
      if (!bytes?.length) throw new Error(`“${scene.title}”缺少配音，请先生成配音后再打开视频`);
      const sha256 = digestVideo(bytes),
        file = `${sha256}.${extension}`;
      await fs.mkdir(videoPath(id, 'assets'), { recursive: true });
      await fs.writeFile(videoPath(id, 'assets', file), bytes, { flag: 'wx' }).catch((e) => {
        if (e.code !== 'EEXIST') throw e;
      });
      audio[action.id] = { file, sha256 };
    }
    if (!Object.keys(audio).length) throw new Error(`“${scene.title}”没有配音，无法生成有声视频`);
    const nativePage = nativePptxPage(classroom.stage, scene);
    const actions = (scene.actions || []).map((a) => {
      const {
        audioId: _id,
        audioUrl: _url,
        ...rest
      } = a as typeof a & { audioId?: string; audioUrl?: string };
      return rest;
    });
    const key = digestVideo(
      canonicalVideo({
        renderer: 1,
        sceneId: scene.id,
        actions,
        audio,
        whiteboard: actions.some((a) => a.type.startsWith('wb_'))
          ? classroom.stage.whiteboard
          : undefined,
        content: nativePage ? undefined : scene.content,
        native: nativePage
          ? {
              page: nativePage,
              source: classroom.stage.nativePptx?.sha256,
              revision: classroom.stage.nativePptx?.renderRevision,
              clicks: classroom.stage.nativePptx?.clicks?.[scene.outlineId || ''],
            }
          : undefined,
      }),
    );
    clips.push({ sceneId: scene.id, key, audio });
  }
  const version = digestVideo(
    canonicalVideo({
      renderer: 1,
      title: classroom.stage.name,
      scenes: scenes.map((s) =>
        s.type === 'slide'
          ? { id: s.id, title: s.title, key: clips.find((c) => c.sceneId === s.id)!.key }
          : s,
      ),
    }),
  );
  const plan: ClassroomVideoPlan = {
    schema: 1,
    id,
    version,
    ownerId,
    createdAt: Date.now(),
    stage: classroom.stage,
    scenes,
    clips,
  };
  if (!(await readVideoPlan(id, version)))
    await writeJsonFileAtomic(videoPath(id, 'versions', `${version}.json`), plan);
  await writeJsonFileAtomic(videoPath(id, 'draft.json'), { version });
  const status = await videoStatus(plan);
  if (status.state !== 'ready') {
    const grant = await signRenderGrant(
      { id, version, exp: Date.now() + 6 * 3600_000 },
      videoSecret(),
    );
    const response = await fetch(`${process.env.CLASSROOM_VIDEO_WORKER_URL}/jobs`, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'x-video-worker-key': process.env.CLASSROOM_VIDEO_WORKER_KEY || '',
      },
      body: JSON.stringify({ id, version, grant, origin }),
      signal: AbortSignal.timeout(10_000),
    });
    if (!response.ok) throw new Error('视频转换服务暂不可用，请重试');
  }
  return plan;
}
export async function nativeVideoConfig(plan: ClassroomVideoPlan, sceneId: string) {
  if (!plan.clips.some((c) => c.sceneId === sceneId)) throw new Error('Invalid scene');
  const url = new URL(
    '/onlyoffice/api/config',
    process.env.ONLYOFFICE_PLAYER_URL || 'http://agentic-onlyoffice-player:3213',
  );
  url.searchParams.set('classroom', plan.id);
  url.searchParams.set('scene', sceneId);
  const response = await fetch(url, {
    headers: internalPlatformHeaders(plan.ownerId),
    signal: AbortSignal.timeout(20_000),
    cache: 'no-store',
  });
  if (!response.ok) throw new Error(`原稿播放器准备失败 (${response.status})`);
  return response.json();
}
export async function preparedVideoForPublication(id: string) {
  const pointer = await videoPointer(id, 'draft');
  if (!pointer) throw new Error('请先点击“全屏打开”，准备并检查视频');
  const plan = await readVideoPlan(id, pointer.version);
  if (!plan || (await videoStatus(plan)).state !== 'ready')
    throw new Error('视频尚未转换完成，请在全屏页面查看进度');
  // Recompute from the current document. Publishing never approves an older edit.
  const latest = await prepareClassroomVideo(
    id,
    plan.ownerId,
    process.env.PLATFORM_PUBLIC_URL || 'http://127.0.0.1:3200',
  );
  if (latest.version !== plan.version) throw new Error('课件已修改，请先检查最新的视频再发布');
  return plan.version;
}
export async function pinPublishedVideo(id: string, version: string) {
  await writeJsonFileAtomic(videoPath(id, 'published.json'), { version });
}
