import { promises as fs } from 'fs';
import path from 'path';
import type { NextRequest } from 'next/server';
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

export async function persistClassroom(
  data: {
    id: string;
    stage: Stage;
    scenes: Scene[];
  },
  baseUrl: string,
): Promise<PersistedClassroomData & { url: string }> {
  const classroomData: PersistedClassroomData = {
    id: data.id,
    stage: data.stage,
    scenes: data.scenes,
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
