import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';
import type { CourseArtifactRecord, CourseSpace } from '@/lib/course-space/types';

let directory = '';
let storage: typeof import('@/lib/server/course-space-storage');
let management: typeof import('@/app/api/course-space/[courseId]/management/route');
let materialRoute: typeof import('@/app/api/course-space/[courseId]/materials/[materialId]/route');
let course: CourseSpace;
let materialId: string;
const context = { params: Promise.resolve({ courseId: 'management-test' }) };
const update = (body: unknown) =>
  management.PATCH(
    new NextRequest('http://localhost/api/management', {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
    context,
  );
const replacement = (text = 'new content') => {
  const form = new FormData();
  form.set('file', new File([text], 'updated.txt', { type: 'text/plain' }));
  return materialRoute.PUT(
    new NextRequest('http://localhost/api/material', { method: 'PUT', body: form }),
    { params: Promise.resolve({ courseId: course.id, materialId }) },
  );
};

beforeEach(async () => {
  directory = await mkdtemp(path.join(tmpdir(), 'course-management-test-'));
  vi.stubEnv('COURSE_SPACES_DATA_DIR', directory);
  vi.stubEnv('COURSE_STORAGE_MODE', 'json');
  vi.stubEnv('COURSE_DATABASE_URL', '');
  vi.stubEnv('DATABASE_URL', '');
  vi.stubEnv('COURSE_OBJECT_STORAGE_MODE', 'database');
  vi.stubEnv('PLATFORM_AUTH_ENABLED', 'false');
  vi.resetModules();
  storage = await import('@/lib/server/course-space-storage');
  management = await import('@/app/api/course-space/[courseId]/management/route');
  materialRoute = await import('@/app/api/course-space/[courseId]/materials/[materialId]/route');
  course = await storage.createServerCourse({
    id: 'management-test',
    teacherId: 'teacher',
    title: '测试课程',
  });
  const material = await storage.storeCourseMaterial({
    courseId: course.id,
    teacherId: course.teacherId,
    fileName: 'source.txt',
    mimeType: 'text/plain',
    bytes: Buffer.from('original content'),
  });
  materialId = material.id;
  course = await storage.updateServerCourse(course.id, (current) => ({
    ...current,
    modules: [
      {
        id: 'module',
        courseId: course.id,
        title: '第一周',
        order: 1,
        objectives: [],
        createdAt: 1,
        updatedAt: 1,
        lessons: [
          {
            id: 'lesson',
            moduleId: 'module',
            title: '第一课',
            order: 1,
            objectives: [],
            materialIds: [materialId],
            createdAt: 1,
            updatedAt: 1,
            files: [
              {
                id: 'file',
                lessonId: 'lesson',
                type: 'knowledge-points',
                title: '知识点',
                content: '正文',
                status: 'ready',
                classPublicationId: 'CLS-file',
                createdAt: 1,
                updatedAt: 1,
              },
            ],
          },
        ],
      },
    ],
  }));
  await storage.saveCourseArtifact({
    id: 'artifact',
    courseId: course.id,
    title: '已发布课件',
    content: '课件正文',
    status: 'published',
    classPublicationId: 'CLS-artifact',
    classVisible: true,
    scope: { type: 'lesson', lessonId: 'lesson' },
    createdAt: 1,
    updatedAt: 1,
  } as CourseArtifactRecord);
});
afterEach(async () => {
  vi.unstubAllEnvs();
  if (
    path.dirname(directory) === path.resolve(tmpdir()) &&
    path.basename(directory).startsWith('course-management-test-')
  )
    await rm(directory, { recursive: true, force: true });
});

describe('persistent workspace file management', () => {
  it.each(['artifacts', 'materials', 'lesson-files', 'modules', 'lessons'])(
    'renames and toggles pin without changing content or publication for %s',
    async (kind) => {
      const id =
        kind === 'artifacts'
          ? 'artifact'
          : kind === 'materials'
            ? materialId
            : kind === 'lesson-files'
              ? 'file'
              : kind === 'modules'
                ? 'module'
                : 'lesson';
      const read = async () => {
        const restored = (await storage.readServerCourse(course.id))!;
        return kind === 'artifacts'
          ? (await storage.readCourseArtifact(id))!
          : kind === 'materials'
            ? restored.materials[0]
            : kind === 'lesson-files'
              ? restored.modules[0].lessons[0].files![0]
              : kind === 'modules'
                ? restored.modules[0]
                : restored.modules[0].lessons[0];
      };
      const before = await read();
      expect((await update({ kind, id, title: '  新名称  ', pinned: true })).status).toBe(200);
      expect(await read()).toEqual({
        ...before,
        [kind === 'materials' ? 'name' : 'title']: kind === 'materials' ? '新名称.txt' : '新名称',
        pinned: true,
        updatedAt: expect.any(Number),
      });
      expect((await update({ kind, id, pinned: false })).status).toBe(200);
      expect((await read()).pinned).toBe(false);
    },
  );
  it.each([
    { title: '' },
    { title: '   ' },
    { title: 'x'.repeat(181) },
    { title: 'bad\nname' },
    { pinned: 'true' },
    { content: 'overwrite' },
    {},
  ])('rejects malformed metadata %j', async (patch) => {
    expect((await update({ kind: 'artifacts', id: 'artifact', ...patch })).status).toBe(400);
    expect((await storage.readCourseArtifact('artifact'))?.title).toBe('已发布课件');
  });
  it('rejects foreign artifacts and absent folders without changing the course', async () => {
    const artifact = (await storage.readCourseArtifact('artifact'))!;
    await storage.saveCourseArtifact({ ...artifact, courseId: 'different-course' });
    expect((await update({ kind: 'artifacts', id: 'artifact', title: 'foreign' })).status).toBe(
      404,
    );
    expect((await update({ kind: 'lessons', id: 'missing', pinned: true })).status).toBe(404);
    expect((await storage.readServerCourse(course.id))?.modules).toEqual(course.modules);
  });
  it('replaces a source file with a new version, preserves location and pin, and keeps original bytes', async () => {
    await update({ kind: 'materials', id: materialId, pinned: true });
    const original = (await storage.readServerCourse(course.id))!.materials[0];
    const response = await replacement();
    expect(response.status).toBe(200);
    const { material } = await response.json();
    expect(material.id).not.toBe(materialId);
    expect(material).toMatchObject({ name: 'updated.txt', pinned: true, status: 'uploaded' });
    const restored = (await storage.readServerCourse(course.id))!;
    expect(restored.materials.map((item) => item.id)).toEqual([material.id]);
    expect(restored.modules[0].lessons[0].materialIds).toEqual([material.id]);
    expect((await storage.readCourseMaterialBytes(material)).toString()).toBe('new content');
    expect((await storage.readCourseMaterialBytes(original)).toString()).toBe('original content');
    expect(material.sha256).not.toBe(original.sha256);
  });
  it.each(['published', 'parsing'])(
    'blocks replacement of %s materials and keeps their references',
    async (state) => {
      await storage.updateServerCourse(course.id, (current) => ({
        ...current,
        materials: current.materials.map((item) => ({
          ...item,
          ...(state === 'published'
            ? { classPublicationId: 'CLS-source' }
            : { status: 'parsing' as const }),
        })),
      }));
      expect((await replacement()).status).toBe(409);
      expect(
        (await storage.readServerCourse(course.id))?.modules[0].lessons[0].materialIds,
      ).toEqual([materialId]);
    },
  );
  it('rejects empty replacement files', async () => {
    expect((await replacement('')).status).toBe(400);
    expect((await storage.readServerCourse(course.id))?.materials[0].id).toBe(materialId);
  });
});
