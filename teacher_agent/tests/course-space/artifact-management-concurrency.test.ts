import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { NextRequest } from 'next/server';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

let directory = '';
let storage: typeof import('@/lib/server/course-space-storage');
let management: typeof import('@/app/api/course-space/[courseId]/management/route');
let editor: typeof import('@/app/api/course-space/[courseId]/artifacts/[artifactId]/route');
let publications: typeof import('@/app/api/course-space/[courseId]/publications/route');
let courseId: string;
const artifactId = 'concurrent-artifact';
const request = (body: unknown, method = 'PATCH') =>
  new NextRequest('http://localhost/api/artifact', {
    method,
    body: JSON.stringify(body),
  });
const context = () => ({ params: Promise.resolve({ courseId, artifactId }) });

beforeEach(async () => {
  directory = await mkdtemp(path.join(tmpdir(), 'course-artifact-concurrency-'));
  vi.stubEnv('COURSE_SPACES_DATA_DIR', directory);
  vi.stubEnv('COURSE_STORAGE_MODE', 'json');
  vi.stubEnv('COURSE_DATABASE_URL', '');
  vi.stubEnv('DATABASE_URL', '');
  vi.stubEnv('COURSE_OBJECT_STORAGE_MODE', 'database');
  vi.stubEnv('PLATFORM_AUTH_ENABLED', 'false');
  vi.resetModules();
  storage = await import('@/lib/server/course-space-storage');
  management = await import('@/app/api/course-space/[courseId]/management/route');
  editor = await import('@/app/api/course-space/[courseId]/artifacts/[artifactId]/route');
  publications = await import('@/app/api/course-space/[courseId]/publications/route');
  const course = await storage.createServerCourse({
    teacherId: 'race-teacher',
    title: 'Concurrent acceptance',
  });
  courseId = course.id;
  await storage.updateServerCourse(courseId, (current) => ({
    ...current,
    status: 'active',
    modules: [
      {
        id: 'race-module',
        courseId,
        title: 'Module',
        order: 1,
        objectives: [],
        createdAt: 1,
        updatedAt: 1,
        lessons: [
          {
            id: 'race-lesson',
            moduleId: 'race-module',
            title: 'Lesson',
            order: 1,
            objectives: [],
            materialIds: [],
            createdAt: 1,
            updatedAt: 1,
          },
        ],
      },
    ],
  }));
  await storage.saveCourseArtifact({
    id: artifactId,
    jobId: 'attached_concurrency',
    teacherId: course.teacherId,
    courseId,
    scope: { type: 'course' },
    type: 'course-outline',
    title: 'Original title',
    content: 'Original content',
    citations: [
      { materialId: 'source', sourceName: 'source.txt', sourceSha256: 'a'.repeat(64), page: 1 },
    ],
    status: 'approved',
    createdAt: Date.now(),
    updatedAt: Date.now(),
  });
});

afterEach(async () => {
  vi.unstubAllEnvs();
  if (
    path.dirname(directory) === path.resolve(tmpdir()) &&
    path.basename(directory).startsWith('course-artifact-concurrency-')
  )
    await rm(directory, { recursive: true, force: true });
});

describe('artifact management concurrent real persistence', () => {
  it('preserves independent rename and pin while rebuilding edited Word content', async () => {
    const [edit, rename] = await Promise.all([
      editor.PATCH(request({ action: 'save', content: 'Edited content' }), context()),
      management.PATCH(
        request({ kind: 'artifacts', id: artifactId, title: 'Renamed title', pinned: true }),
        context(),
      ),
    ]);
    expect(edit.status).toBe(200);
    expect(rename.status).toBe(200);
    const restored = (await storage.readCourseArtifact(artifactId))!;
    expect(restored).toMatchObject({
      title: 'Renamed title',
      pinned: true,
      content: 'Edited content',
      status: 'review',
    });
    expect(restored.wordFileName).toBe('Renamed title.docx');
    expect((await storage.readCourseArtifactFile(restored.wordStorageKey!)).length).toBeGreaterThan(
      0,
    );
  });

  it('serializes generic publication with an in-flight text save without losing publication', async () => {
    const [published, edited] = await Promise.all([
      publications.POST(
        request(
          {
            kind: 'artifact',
            id: artifactId,
            placement: {
              lessonId: 'race-lesson',
              week: 1,
              lessonNumber: 1,
              teachingHours: 2,
              resourceType: 'outline',
            },
          },
          'POST',
        ),
        context(),
      ),
      editor.PATCH(request({ action: 'save', content: 'Concurrent edited content' }), context()),
    ]);
    expect(published.status).toBe(200);
    expect([200, 409]).toContain(edited.status);
    const restored = (await storage.readCourseArtifact(artifactId))!;
    expect(restored).toMatchObject({
      status: 'published',
      classVisible: true,
      publicationPlacement: { lessonId: 'race-lesson' },
    });
    expect(restored.classPublicationId).toMatch(/^CLS-A-/);
    expect(restored.content).toBe(
      edited.status === 200 ? 'Concurrent edited content' : 'Original content',
    );
    expect(
      (await editor.PATCH(request({ action: 'save', content: 'Must remain rejected' }), context()))
        .status,
    ).toBe(409);
  });

  it('preserves metadata and publication while a course read backfills legacy Word files', async () => {
    const [listed, renamed, published] = await Promise.all([
      storage.listCourseArtifacts(courseId),
      management.PATCH(
        request({ kind: 'artifacts', id: artifactId, title: 'Renamed legacy title', pinned: true }),
        context(),
      ),
      publications.POST(
        request(
          {
            kind: 'artifact',
            id: artifactId,
            placement: {
              lessonId: 'race-lesson',
              week: 1,
              lessonNumber: 1,
              teachingHours: 2,
              resourceType: 'outline',
            },
          },
          'POST',
        ),
        context(),
      ),
    ]);
    expect(listed).toHaveLength(1);
    expect(renamed.status).toBe(200);
    expect(published.status).toBe(200);
    const restored = (await storage.readCourseArtifact(artifactId))!;
    expect(restored).toMatchObject({
      title: 'Renamed legacy title',
      pinned: true,
      status: 'published',
      classVisible: true,
    });
    expect(restored.classPublicationId).toMatch(/^CLS-A-/);
    expect(restored.wordFileName).toBe('Renamed legacy title.docx');
    expect((await storage.readCourseArtifactFile(restored.wordStorageKey!)).length).toBeGreaterThan(
      0,
    );
  });
});
