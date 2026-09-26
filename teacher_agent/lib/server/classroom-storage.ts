import { promises as fs } from 'fs';
import path from 'path';
import type { NextRequest } from 'next/server';
import type { Action } from '@/lib/types/action';
import type { Scene, Stage } from '@/lib/types/stage';
import {
  isCourseDatabaseConfigured,
  readClassroomFromDatabase,
  upsertClassroomDatabaseRecord,
} from '@/lib/server/course-space-database';

export const CLASSROOMS_DIR = process.env.CLASSROOMS_DATA_DIR
  ? path.resolve(process.env.CLASSROOMS_DATA_DIR)
  : path.join(process.cwd(), 'data', 'classrooms');
export const CLASSROOM_JOBS_DIR = process.env.CLASSROOM_JOBS_DATA_DIR
  ? path.resolve(process.env.CLASSROOM_JOBS_DATA_DIR)
  : path.join(process.cwd(), 'data', 'classroom-jobs');

async function ensureDir(dir: string) {
  await fs.mkdir(dir, { recursive: true });
}

export async function ensureClassroomsDir() {
  await ensureDir(CLASSROOMS_DIR);
}

export async function ensureClassroomJobsDir() {
  await ensureDir(CLASSROOM_JOBS_DIR);
}

export async function writeJsonFileAtomic(filePath: string, data: unknown) {
  const dir = path.dirname(filePath);
  await ensureDir(dir);

  const tempFilePath = `${filePath}.${process.pid}.${Date.now()}.tmp`;
  const content = JSON.stringify(data, null, 2);
  await fs.writeFile(tempFilePath, content, 'utf-8');
  await fs.rename(tempFilePath, filePath);
}

export function buildRequestOrigin(req: NextRequest): string {
  return req.headers.get('x-forwarded-host')
    ? `${req.headers.get('x-forwarded-proto') || 'http'}://${req.headers.get('x-forwarded-host')}`
    : req.nextUrl.origin;
}

export interface PersistedClassroomData {
  id: string;
  stage: Stage;
  scenes: Scene[];
  createdAt: string;
}

export function isValidClassroomId(id: string): boolean {
  return /^[a-zA-Z0-9_-]+$/.test(id);
}

/** Resolve a classroom file while enforcing containment inside CLASSROOMS_DIR. */
export function resolveClassroomFilePath(id: string): string {
  const resolvedRoot = path.resolve(CLASSROOMS_DIR);
  const filePath = path.resolve(resolvedRoot, `${id}.json`);
  const rootPrefix = `${resolvedRoot}${path.sep}`;
  if (filePath !== resolvedRoot && !filePath.startsWith(rootPrefix)) {
    throw new Error(`Classroom id "${id}" resolves outside the classrooms directory`);
  }
  return filePath;
}

export async function readClassroom(id: string): Promise<PersistedClassroomData | null> {
  const databaseClassroom = await readClassroomFromDatabase(id);
  if (isCourseDatabaseConfigured()) return databaseClassroom ?? null;
  const filePath = resolveClassroomFilePath(id);
  try {
    const content = await fs.readFile(filePath, 'utf-8');
    return JSON.parse(content) as PersistedClassroomData;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
      return null;
    }
    throw error;
  }
}

/** Extensions the TTS writers may persist, in lookup order. */
const NARRATION_EXTENSIONS = ['wav', 'mp3', 'ogg', 'aac'] as const;

/** True when a segment is safe to build a media filename from. */
function isSafeNarrationToken(token: string | undefined): token is string {
  return !!token && /^[A-Za-z0-9_-]+$/.test(token);
}

/**
 * Resolve the persisted narration file behind a speech action, if one exists.
 *
 * Both TTS writers — the server narration route and the browser-side
 * `/api/generate/tts` upload — name files `tts_s<sceneOrder>_<actionId>.<ext>`,
 * so the serving URL can be re-derived from the action identity alone. This is
 * what keeps a classroom self-contained across browser round-trips: the client
 * document stores pool-allocated `ast_*` ids (and drops the URL on
 * conversion), so without re-stamping, a save from a converted document would
 * leave the server copy referencing audio only that one browser ever had.
 */
async function resolveNarrationUrl(
  classroomId: string,
  sceneOrder: number,
  actionId: string,
  baseUrl: string,
): Promise<string | undefined> {
  for (const ext of NARRATION_EXTENSIONS) {
    const filePath = path.join(
      CLASSROOMS_DIR,
      classroomId,
      'audio',
      `tts_s${sceneOrder}_${actionId}.${ext}`,
    );
    try {
      const stat = await fs.stat(filePath);
      if (stat.isFile()) {
        // The version token changes when the file is regenerated in place, so
        // a browser that already converted this URL allocates a fresh asset
        // instead of reusing its mirror for superseded bytes.
        const version = `${stat.size}-${Math.trunc(stat.mtimeMs)}`;
        return `${baseUrl}/api/classroom-media/${classroomId}/audio/tts_s${sceneOrder}_${actionId}.${ext}?v=${version}`;
      }
    } catch {
      // Missing candidate extension — try the next.
    }
  }
  return undefined;
}

interface SpeechActionLike {
  type: string;
  id?: string;
  audioId?: string;
  audioUrl?: string;
  audioInvalidated?: boolean;
}

/**
 * Stamp serving URLs onto speech actions whose narration exists on disk but
 * whose reference a browser round-trip reduced to a pool-local id. Actions that
 * already carry a URL (server-generated narration) and id-less actions are left
 * untouched. Returns the input by identity when nothing resolved.
 */
export async function attachNarrationServingUrls(
  scenes: Scene[],
  classroomId: string,
  baseUrl: string,
): Promise<Scene[]> {
  let changed = false;
  const nextScenes: Scene[] = [];
  for (const scene of scenes) {
    if (
      !scene.actions?.some((a) => a.type === 'speech' && (a as SpeechActionLike).audioId) ||
      typeof scene.order !== 'number'
    ) {
      nextScenes.push(scene);
      continue;
    }
    const nextActions: Action[] = [];
    let sceneChanged = false;
    for (const action of scene.actions) {
      const speech = action as Action & SpeechActionLike;
      // `audioInvalidated` is a text-staleness hint, not a statement that no
      // audio exists: browser regeneration writes fresh bytes under the
      // derived filename even when the flag survives a stale save. When the
      // file is there, stamping the URL keeps every browser hearing exactly
      // what the editing teacher hears.
      if (
        speech.type === 'speech' &&
        speech.audioId &&
        !speech.audioUrl &&
        isSafeNarrationToken(speech.id)
      ) {
        const audioUrl = await resolveNarrationUrl(classroomId, scene.order, speech.id, baseUrl);
        if (audioUrl) {
          sceneChanged = true;
          nextActions.push({ ...speech, audioUrl } as Action);
          continue;
        }
      }
      nextActions.push(action);
    }
    nextScenes.push(sceneChanged ? { ...scene, actions: nextActions } : scene);
    if (sceneChanged) changed = true;
  }
  return changed ? nextScenes : scenes;
}

export async function persistClassroom(
  data: {
    id: string;
    stage: Stage;
    scenes: Scene[];
  },
  baseUrl: string,
): Promise<PersistedClassroomData & { url: string }> {
  // Re-attach serving URLs a browser round-trip dropped: converted client
  // documents carry pool-local ast_* ids with no URL, and persisting those
  // verbatim would strand the narration on the editing browser. See
  // attachNarrationServingUrls.
  const scenes = await attachNarrationServingUrls(data.scenes, data.id, baseUrl);
  const classroomData: PersistedClassroomData = {
    id: data.id,
    stage: data.stage,
    scenes,
    createdAt: new Date().toISOString(),
  };

  if (!isCourseDatabaseConfigured()) {
    const filePath = resolveClassroomFilePath(data.id);
    await ensureClassroomsDir();
    await writeJsonFileAtomic(filePath, classroomData);
  }
  await upsertClassroomDatabaseRecord(classroomData);

  return {
    ...classroomData,
    url: `${baseUrl}/classroom/${data.id}`,
  };
}
