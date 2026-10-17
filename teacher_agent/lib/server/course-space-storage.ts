import { createHash } from 'crypto';
import { promises as fs } from 'fs';
import path from 'path';
import { nanoid } from 'nanoid';
import { writeJsonFileAtomic } from '@/lib/server/classroom-storage';
import { generateCourseId, resolveLegacyCourseId } from '@/lib/server/platform-course-bridge';
import type {
  CourseArtifactJob,
  CourseArtifactRecord,
  CourseMaterialExtraction,
  CourseMaterialRecord,
  CourseSpace,
  CreateCourseSpaceInput,
  PublishedKnowledgePackage,
} from '@/lib/course-space/types';
import { markdownToArtifactHtml, WORD_ARTIFACT_TYPES } from '@/lib/course-space/artifact-formats';
import { buildCourseArtifactDocx } from '@/lib/server/course-artifact-docx';
import { getCourseSpaceStorageAdapter } from '@/lib/server/course-space-storage-adapter';
import {
  isCourseObjectStorageEnabled,
  putCourseObject,
  readCourseObject,
} from '@/lib/server/course-object-storage';
import {
  assertCourseDatabaseReady,
  isCourseDatabaseConfigured,
  listActiveCourseJobsFromDatabase,
  listCoursesFromDatabase,
  listCourseJobsFromDatabase,
  listKnowledgePackagesFromDatabase,
  readArtifactFileFromDatabase,
  readCourseFromDatabase,
  readCourseArtifactFromDatabase,
  readCourseJobFromDatabase,
  readCourseMaterialFileFromDatabase,
  readKnowledgePackageFromDatabase,
  readMaterialExtractionFromDatabase,
  upsertArtifactFileDatabaseRecord,
  upsertCourseMaterialFileDatabaseRecord,
} from '@/lib/server/course-space-database';

const databaseAdapter = getCourseSpaceStorageAdapter();
// Fail fast on a misconfigured postgres mode instead of silently using JSON.
assertCourseDatabaseReady();

export const COURSE_SPACES_DIR = process.env.COURSE_SPACES_DATA_DIR
  ? path.resolve(process.env.COURSE_SPACES_DATA_DIR)
  : path.join(process.cwd(), 'data', 'course-spaces');
const COURSES_DIR = path.join(COURSE_SPACES_DIR, 'courses');
const MATERIALS_DIR = path.join(COURSE_SPACES_DIR, 'materials');
const JOBS_DIR = path.join(COURSE_SPACES_DIR, 'jobs');
const ARTIFACTS_DIR = path.join(COURSE_SPACES_DIR, 'artifacts');
const ARTIFACT_FILES_DIR = path.join(COURSE_SPACES_DIR, 'artifact-files');
const KNOWLEDGE_DIR = path.join(COURSE_SPACES_DIR, 'knowledge-packages');

const locks = new Map<string, Promise<void>>();

async function withLock<T>(key: string, fn: () => Promise<T>): Promise<T> {
  const previous = locks.get(key) ?? Promise.resolve();
  let release!: () => void;
  const current = new Promise<void>((resolve) => (release = resolve));
  locks.set(key, current);
  try {
    await previous;
    return await fn();
  } finally {
    release();
    if (locks.get(key) === current) locks.delete(key);
  }
}

function validId(id: string) {
  return /^[a-zA-Z0-9_-]+$/.test(id);
}

function assertId(id: string, label: string) {
  if (!validId(id)) throw new Error(`Invalid ${label}`);
}

async function readJson<T>(filePath: string): Promise<T | null> {
  try {
    return JSON.parse(await fs.readFile(filePath, 'utf8')) as T;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return null;
    throw error;
  }
}

async function listJson<T>(dir: string): Promise<T[]> {
  try {
    const files = (await fs.readdir(dir)).filter((name) => name.endsWith('.json'));
    const values = await Promise.all(files.map((name) => readJson<T>(path.join(dir, name))));
    return values.reduce<T[]>((items, item) => (item === null ? items : [...items, item]), []);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return [];
    throw error;
  }
}

export async function listServerCourses(teacherId: string): Promise<CourseSpace[]> {
  const databaseCourses = await listCoursesFromDatabase(teacherId);
  if (databaseCourses) return databaseCourses.filter((course) => !course.deletedAt);
  return (await listJson<CourseSpace>(COURSES_DIR))
    .filter((course) => course.teacherId === teacherId && !course.deletedAt)
    .sort((a, b) => b.updatedAt - a.updatedAt);
}

export async function readServerCourse(courseId: string): Promise<CourseSpace | null> {
  const course = await readStoredCourse(courseId);
  return course && !course.deletedAt ? course : null;
}

async function readStoredCourse(courseId: string): Promise<CourseSpace | null> {
  assertId(courseId, 'course id');
  const direct = await readStoredCourseById(courseId);
  if (direct) return direct;
  // Platform entry points may still carry the UUID of a legacy teacher course.
  const legacyId = await resolveLegacyCourseId(courseId);
  return legacyId ? readStoredCourseById(legacyId) : null;
}

async function readStoredCourseById(courseId: string): Promise<CourseSpace | null> {
  const databaseCourse = await readCourseFromDatabase(courseId);
  if (databaseCourse) return databaseCourse;
  if (!isCourseDatabaseConfigured()) {
    const localCourse = await readJson<CourseSpace>(path.join(COURSES_DIR, `${courseId}.json`));
    if (localCourse) return localCourse;
  }
  return null;
}

export async function createServerCourse(input: CreateCourseSpaceInput): Promise<CourseSpace> {
  const now = Date.now();
  const course: CourseSpace = {
    id: generateCourseId(input.id),
    teacherId: input.teacherId,
    title: input.title.trim(),
    subject: input.subject?.trim() || undefined,
    gradeBand: input.gradeBand?.trim() || undefined,
    term: input.term?.trim() || undefined,
    description: input.description?.trim() || undefined,
    status: 'draft',
    onboarding: { version: 1, step: 1 },
    modules: [],
    materials: [],
    createdAt: now,
    updatedAt: now,
  };
  return withLock(`course:${course.id}`, async () => {
    if (await readStoredCourseById(course.id)) throw new Error('课程标识已存在，请重新创建课程');
    return writeServerCourse(course);
  });
}

export async function saveServerCourse(course: CourseSpace): Promise<CourseSpace> {
  assertId(course.id, 'course id');
  return withLock(`course:${course.id}`, async () => {
    const existing = await readStoredCourse(course.id);
    if (existing?.deletedAt) throw new Error('课程已删除，请返回课程中心');
    return writeServerCourse({ ...course, deletedAt: existing?.deletedAt });
  });
}

async function writeServerCourse(course: CourseSpace): Promise<CourseSpace> {
  const saved = { ...course, updatedAt: Date.now() };
  if (!isCourseDatabaseConfigured())
    await writeJsonFileAtomic(path.join(COURSES_DIR, `${course.id}.json`), saved);
  await databaseAdapter.saveCourse(saved);
  return saved;
}

export async function updateServerCourse(
  courseId: string,
  update: (course: CourseSpace) => CourseSpace | Promise<CourseSpace>,
): Promise<CourseSpace> {
  const initial = await readServerCourse(courseId);
  if (!initial) throw new Error('Course not found');
  return withLock(`course:${initial.id}`, async () => {
    const course = await readServerCourse(initial.id);
    if (!course) throw new Error('Course not found');
    return writeServerCourse(await update(course));
  });
}

export class CourseDeletionConflict extends Error {}

/** Keep bytes and a tombstone so stale browser saves cannot resurrect a deleted course. */
export async function deleteServerCourse(courseId: string): Promise<void> {
  const course = await readStoredCourse(courseId);
  if (!course || course.deletedAt) return;
  await withLock(`course:${course.id}`, async () => {
    const current = await readStoredCourse(course.id);
    if (!current || current.deletedAt) return;
    const jobs = await listCourseJobs(current.id);
    if (
      jobs.some((job) => ['queued', 'running'].includes(job.status) && !isStaleActiveJob(job)) ||
      current.materials.some((material) => material.status === 'parsing')
    ) {
      throw new CourseDeletionConflict('课程仍有生成或解析任务，请等待任务结束后再删除');
    }
    await writeServerCourse({ ...current, status: 'archived', deletedAt: Date.now() });
  });
}

export async function storeCourseMaterial(input: {
  purpose?: 'course-material' | 'course-outline';
  courseId: string;
  teacherId: string;
  fileName: string;
  mimeType: string;
  bytes: Buffer;
}): Promise<CourseMaterialRecord> {
  assertId(input.courseId, 'course id');
  const id = nanoid(14);
  const extension = path.extname(input.fileName).slice(0, 12);
  const materialDir = path.join(MATERIALS_DIR, id);
  if (!isCourseDatabaseConfigured()) {
    await fs.mkdir(materialDir, { recursive: true });
    await fs.writeFile(path.join(materialDir, `source${extension}`), input.bytes);
  }
  const now = Date.now();
  const record: CourseMaterialRecord = {
    id,
    purpose: input.purpose ?? 'course-material',
    teacherId: input.teacherId,
    courseId: input.courseId,
    name: path.basename(input.fileName),
    mimeType: input.mimeType,
    size: input.bytes.length,
    storageKey: isCourseObjectStorageEnabled()
      ? `materials/${input.courseId}/${id}/source${extension}`
      : `${id}/source${extension}`,
    sha256: createHash('sha256').update(input.bytes).digest('hex'),
    status: 'uploaded',
    createdAt: now,
    updatedAt: now,
  };
  await updateServerCourse(input.courseId, (course) => ({
    ...course,
    materials: [...course.materials, record],
  }));
  if (isCourseObjectStorageEnabled()) {
    await putCourseObject(record.storageKey, input.bytes, record.mimeType);
  }
  await upsertCourseMaterialFileDatabaseRecord({
    storageKey: record.storageKey,
    materialId: record.id,
    courseId: record.courseId,
    fileName: record.name,
    mimeType: record.mimeType,
    bytes: isCourseObjectStorageEnabled() ? undefined : input.bytes,
    sizeBytes: input.bytes.length,
    sha256: record.sha256!,
  });
  return record;
}

export async function readCourseMaterialBytes(record: CourseMaterialRecord): Promise<Buffer> {
  if (isCourseObjectStorageEnabled()) {
    const objectBytes = await readCourseObject(record.storageKey);
    if (objectBytes) return objectBytes;
  }
  const databaseBytes = await readCourseMaterialFileFromDatabase(record.storageKey);
  if (databaseBytes) return databaseBytes;
  if (isCourseDatabaseConfigured()) throw new Error('Material file missing from database');
  const resolved = path.resolve(MATERIALS_DIR, record.storageKey);
  if (!resolved.startsWith(path.resolve(MATERIALS_DIR) + path.sep))
    throw new Error('Invalid material path');
  return fs.readFile(resolved);
}

export async function saveMaterialExtraction(extraction: CourseMaterialExtraction) {
  assertId(extraction.materialId, 'material id');
  if (!isCourseDatabaseConfigured())
    await writeJsonFileAtomic(
      path.join(MATERIALS_DIR, extraction.materialId, 'extraction.json'),
      extraction,
    );
  await databaseAdapter.saveMaterialExtraction(extraction);
}

export async function readMaterialExtraction(materialId: string) {
  assertId(materialId, 'material id');
  if (isCourseDatabaseConfigured())
    return (await readMaterialExtractionFromDatabase(materialId)) ?? null;
  return readJson<CourseMaterialExtraction>(
    path.join(MATERIALS_DIR, materialId, 'extraction.json'),
  );
}

export async function saveCourseJob(job: CourseArtifactJob): Promise<CourseArtifactJob> {
  assertId(job.id, 'job id');
  if (!isCourseDatabaseConfigured())
    await writeJsonFileAtomic(path.join(JOBS_DIR, `${job.id}.json`), job);
  await databaseAdapter.saveJob(job);
  return job;
}

export async function readCourseJob(jobId: string) {
  assertId(jobId, 'job id');
  if (isCourseDatabaseConfigured()) return (await readCourseJobFromDatabase(jobId)) ?? null;
  return readJson<CourseArtifactJob>(path.join(JOBS_DIR, `${jobId}.json`));
}

export async function updateCourseJob(jobId: string, patch: Partial<CourseArtifactJob>) {
  return withLock(`job:${jobId}`, async () => {
    const job = await readCourseJob(jobId);
    if (!job) throw new Error('Job not found');
    return saveCourseJob({ ...job, ...patch, updatedAt: Date.now() });
  });
}

/**
 * Attached courseware artifacts reference a synthetic `attached_*` jobId that has no job
 * record; artifact review/activation must not fail on those. Generation-flow callers
 * keep the strict updateCourseJob semantics.
 */
export async function updateCourseJobIfPresent(jobId: string, patch: Partial<CourseArtifactJob>) {
  return withLock(`job:${jobId}`, async () => {
    const job = await readCourseJob(jobId);
    if (!job) return null;
    return saveCourseJob({ ...job, ...patch, updatedAt: Date.now() });
  });
}

export async function listCourseJobs(courseId: string) {
  if (isCourseDatabaseConfigured()) return (await listCourseJobsFromDatabase(courseId)) ?? [];
  return (await listJson<CourseArtifactJob>(JOBS_DIR))
    .filter((job) => job.courseId === courseId)
    .sort((a, b) => b.createdAt - a.createdAt);
}

/**
 * A queued/running job with no update for this long is considered dead — its
 * process died with a container restart or a wedged LLM call. Without a sweep
 * such jobs stay "running" forever in the teacher UI (only a same-scope
 * resubmit used to clear them).
 */
export const STALE_ACTIVE_JOB_MS = 15 * 60 * 1000;

export const STALE_ACTIVE_JOB_FAILURE = {
  status: 'failed' as const,
  progress: 100,
  message: '生成进程已中断，可重新创建任务',
  error: '后台生成进程中断或服务重启，任务未能继续执行',
};

export function isStaleActiveJob(job: CourseArtifactJob, now = Date.now()) {
  return (
    (job.status === 'queued' || job.status === 'running') &&
    now - job.updatedAt > STALE_ACTIVE_JOB_MS
  );
}

/** Mark the stale active jobs in `jobs` failed; returns the ones it touched. */
export async function markStaleCourseJobsFailed(jobs: CourseArtifactJob[]) {
  const stale = jobs.filter((job) => isStaleActiveJob(job));
  await Promise.all(stale.map((job) => updateCourseJob(job.id, STALE_ACTIVE_JOB_FAILURE)));
  return stale;
}

export async function sweepStaleCourseJobs(courseId: string) {
  return markStaleCourseJobsFailed(await listCourseJobs(courseId));
}

/** Startup sweep across every course: restarts kill in-flight jobs mid-run. */
export async function sweepAllStaleCourseJobs() {
  const active = isCourseDatabaseConfigured()
    ? ((await listActiveCourseJobsFromDatabase()) ?? [])
    : (await listJson<CourseArtifactJob>(JOBS_DIR)).filter(
        (job) => job.status === 'queued' || job.status === 'running',
      );
  return markStaleCourseJobsFailed(active);
}

export async function saveCourseArtifact(artifact: CourseArtifactRecord) {
  assertId(artifact.id, 'artifact id');
  if (!isCourseDatabaseConfigured())
    await writeJsonFileAtomic(path.join(ARTIFACTS_DIR, `${artifact.id}.json`), artifact);
  await databaseAdapter.saveArtifact(artifact);
  return artifact;
}

export async function saveCourseArtifactFile(artifactId: string, fileName: string, bytes: Buffer) {
  assertId(artifactId, 'artifact id');
  const safeName = path.basename(fileName);
  const dir = path.join(ARTIFACT_FILES_DIR, artifactId);
  if (!isCourseDatabaseConfigured()) {
    await fs.mkdir(dir, { recursive: true });
    await fs.writeFile(path.join(dir, safeName), bytes);
  }
  const storageKey = isCourseObjectStorageEnabled()
    ? `artifacts/${artifactId}/${safeName}`
    : `${artifactId}/${safeName}`;
  const extension = path.extname(safeName).toLowerCase();
  const mimeType =
    extension === '.docx'
      ? 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
      : extension === '.pdf'
        ? 'application/pdf'
        : 'application/octet-stream';
  if (isCourseObjectStorageEnabled()) await putCourseObject(storageKey, bytes, mimeType);
  await upsertArtifactFileDatabaseRecord({
    storageKey,
    artifactId,
    fileName: safeName,
    mimeType,
    bytes: isCourseObjectStorageEnabled() ? undefined : bytes,
    sizeBytes: bytes.length,
    sha256: createHash('sha256').update(bytes).digest('hex'),
  });
  return storageKey;
}

export async function readCourseArtifactFile(storageKey: string) {
  if (isCourseObjectStorageEnabled()) {
    const objectBytes = await readCourseObject(storageKey);
    if (objectBytes) return objectBytes;
  }
  const databaseFile = await readArtifactFileFromDatabase(storageKey);
  if (databaseFile?.bytes) return databaseFile.bytes;
  if (isCourseDatabaseConfigured()) throw new Error('Artifact file missing from database');
  const resolved = path.resolve(ARTIFACT_FILES_DIR, storageKey);
  if (!resolved.startsWith(path.resolve(ARTIFACT_FILES_DIR) + path.sep))
    throw new Error('Invalid artifact file path');
  return fs.readFile(resolved);
}

export async function readCourseArtifact(artifactId: string) {
  assertId(artifactId, 'artifact id');
  const databaseArtifact = await readCourseArtifactFromDatabase(artifactId);
  if (isCourseDatabaseConfigured()) return databaseArtifact ?? null;
  return readJson<CourseArtifactRecord>(path.join(ARTIFACTS_DIR, `${artifactId}.json`));
}

export async function deleteCourseArtifact(artifactId: string) {
  assertId(artifactId, 'artifact id');
  const artifact = await readCourseArtifact(artifactId);
  if (!artifact) return false;
  await fs.rm(path.join(ARTIFACT_FILES_DIR, artifactId), { recursive: true, force: true });
  await fs.rm(path.join(ARTIFACTS_DIR, `${artifactId}.json`), { force: true });
  await databaseAdapter.deleteArtifact(artifactId);
  return true;
}

export async function listCourseArtifacts(courseId: string) {
  const databaseArtifacts = await databaseAdapter.listArtifacts(courseId);
  const artifacts = (databaseArtifacts ?? (await listJson<CourseArtifactRecord>(ARTIFACTS_DIR)))
    .filter((artifact) => artifact.courseId === courseId)
    .sort((a, b) => b.createdAt - a.createdAt);
  return Promise.all(
    artifacts.map(async (artifact) => {
      let changed = false;
      if (!artifact.htmlContent) {
        artifact.htmlContent = markdownToArtifactHtml(artifact.content);
        changed = true;
      }
      if (WORD_ARTIFACT_TYPES.has(artifact.type) && !artifact.wordStorageKey) {
        const wordFileName = `${artifact.title.replace(/[\\/:*?"<>|]/g, '_')}.docx`;
        artifact.wordFileName = wordFileName;
        artifact.wordStorageKey = await saveCourseArtifactFile(
          artifact.id,
          wordFileName,
          await buildCourseArtifactDocx(artifact.title, artifact.content),
        );
        changed = true;
      }
      if (changed) await saveCourseArtifact(artifact);
      return artifact;
    }),
  );
}

export async function saveKnowledgePackage(pkg: PublishedKnowledgePackage) {
  assertId(pkg.id, 'knowledge package id');
  if (!isCourseDatabaseConfigured())
    await writeJsonFileAtomic(path.join(KNOWLEDGE_DIR, `${pkg.id}.json`), pkg);
  await databaseAdapter.saveKnowledgePackage(pkg);
  return pkg;
}

export async function readKnowledgePackage(packageId: string) {
  assertId(packageId, 'knowledge package id');
  if (isCourseDatabaseConfigured())
    return (await readKnowledgePackageFromDatabase(packageId)) ?? null;
  return readJson<PublishedKnowledgePackage>(path.join(KNOWLEDGE_DIR, `${packageId}.json`));
}

export async function listKnowledgePackages(courseId: string) {
  if (isCourseDatabaseConfigured())
    return (await listKnowledgePackagesFromDatabase(courseId)) ?? [];
  return (await listJson<PublishedKnowledgePackage>(KNOWLEDGE_DIR))
    .filter((pkg) => pkg.courseId === courseId)
    .sort((a, b) => b.version - a.version);
}

export async function readPublishedKnowledgePackage(courseId: string) {
  const databasePackage = await databaseAdapter.readPublishedKnowledgePackage(courseId);
  if (databasePackage) return databasePackage;
  return (await listKnowledgePackages(courseId)).find((pkg) => pkg.status === 'published');
}
