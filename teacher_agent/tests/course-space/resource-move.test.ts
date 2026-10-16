import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';
import type { CourseArtifactRecord, CourseSpace } from '@/lib/course-space/types';

const storage = vi.hoisted(() => ({
  readServerCourse: vi.fn(),
  updateServerCourse: vi.fn(),
  listCourseArtifacts: vi.fn(),
  readCourseArtifact: vi.fn(),
  saveCourseArtifact: vi.fn(),
  deleteCourseArtifact: vi.fn(),
  readCourseMaterialBytes: vi.fn(),
}));
vi.mock('@/lib/server/course-space-storage', () => storage);
import { POST } from '@/app/api/course-space/[courseId]/tree/route';
import * as materials from '@/app/api/course-space/[courseId]/materials/[materialId]/route';
import * as files from '@/app/api/course-space/[courseId]/lesson-files/[fileId]/route';

let course: CourseSpace;
let artifact: CourseArtifactRecord;
const context = { params: Promise.resolve({ courseId: 'platform-alias' }) };
const request = (body: unknown) =>
  new NextRequest('http://localhost/api/tree', {
    method: 'POST',
    body: JSON.stringify(body),
  });
const move = (itemKind: string, itemId = 'resource', targetLessonId = 'target') =>
  POST(request({ action: 'move-item', itemKind, itemId, targetLessonId }), context);
const lesson = (id: string) =>
  course.modules.flatMap((module) => module.lessons).find((item) => item.id === id)!;

beforeEach(() => {
  vi.resetAllMocks();
  course = {
    id: 'canonical',
    status: 'active',
    materials: [
      { id: 'resource', status: 'ready', classVisible: true, classPublicationId: 'CLS-M-old' },
    ],
    modules: [
      {
        id: 'module-a',
        lessons: [
          {
            id: 'source',
            materialIds: ['resource'],
            files: [
              {
                id: 'resource',
                lessonId: 'source',
                type: 'lesson-objectives',
                title: '课程目标',
                content: '目标内容',
                classVisible: true,
                classPublicationId: 'CLS-F-old',
              },
            ],
          },
        ],
      },
      { id: 'module-b', lessons: [{ id: 'target', materialIds: [], files: [] }] },
    ],
  } as unknown as CourseSpace;
  artifact = {
    id: 'resource',
    courseId: 'canonical',
    scope: { type: 'lesson', lessonId: 'source' },
    status: 'published',
    content: '课件内容',
    classVisible: true,
    classPublicationId: 'CLS-A-old',
  } as CourseArtifactRecord;
  storage.readServerCourse.mockImplementation(async () => course);
  storage.updateServerCourse.mockImplementation(async (_id, update) => (course = update(course)));
  storage.listCourseArtifacts.mockImplementation(async () => [artifact]);
  storage.readCourseArtifact.mockImplementation(async () => artifact);
  storage.saveCourseArtifact.mockImplementation(async (value) => (artifact = value));
});

describe('move resources within a course', () => {
  it.each(['artifact', 'material', 'course-file'] as const)(
    'updates the confirmed lesson binding when moving a published %s',
    async (kind) => {
      const resource =
        kind === 'artifact'
          ? artifact
          : kind === 'material'
            ? course.materials[0]
            : lesson('source').files![0];
      resource.publicationPlacement = {
        lessonId: 'source',
        week: 1,
        lessonNumber: 1,
        teachingHours: 2,
        resourceType: 'material',
        confirmedAt: 1,
      };
      Object.assign(lesson('target'), { week: 2, lessonNumber: 3, teachingHours: 1 });
      const publicationId = resource.classPublicationId;
      expect((await move(kind)).status).toBe(200);
      const moved =
        kind === 'artifact'
          ? artifact
          : kind === 'material'
            ? course.materials[0]
            : lesson('target').files![0];
      expect(moved.classPublicationId).toBe(publicationId);
      expect(moved.publicationPlacement).toMatchObject({
        lessonId: 'target',
        week: 2,
        lessonNumber: 3,
        teachingHours: 1,
      });
    },
  );

  it.each(['artifact', 'material', 'course-file'] as const)(
    'does not leave a stale publication binding when the destination lacks scheduling: %s',
    async (kind) => {
      const resource =
        kind === 'artifact'
          ? artifact
          : kind === 'material'
            ? course.materials[0]
            : lesson('source').files![0];
      resource.publicationPlacement = {
        lessonId: 'source',
        week: 1,
        lessonNumber: 1,
        teachingHours: 2,
        resourceType: 'material',
        confirmedAt: 1,
      };
      expect((await move(kind)).status).toBe(409);
      expect(storage.saveCourseArtifact).not.toHaveBeenCalled();
      expect(storage.updateServerCourse).not.toHaveBeenCalled();
    },
  );

  it('retains the main branch protection against deleting a folder containing published resources', async () => {
    expect(
      (await POST(request({ action: 'delete-lesson', lessonId: 'source' }), context)).status,
    ).toBe(409);
    expect(storage.deleteCourseArtifact).not.toHaveBeenCalled();
    expect(storage.updateServerCourse).not.toHaveBeenCalled();
  });

  it('resolves the platform course alias and moves published courseware without changing its content or publication', async () => {
    const original = structuredClone(artifact);
    expect((await move('artifact')).status).toBe(200);
    expect(artifact).toMatchObject({ ...original, scope: { type: 'lesson', lessonId: 'target' } });
    expect(storage.listCourseArtifacts).not.toHaveBeenCalled();
  });

  it('moves material references once, then allows withdrawal and deletion at the destination', async () => {
    lesson('target').materialIds = ['resource'];
    expect((await move('material')).status).toBe(200);
    expect(lesson('source').materialIds).toEqual([]);
    expect(lesson('target').materialIds).toEqual(['resource']);
    expect(course.materials[0].classPublicationId).toBe('CLS-M-old');
    expect(storage.updateServerCourse).toHaveBeenCalledWith('canonical', expect.any(Function));
    const params = {
      params: Promise.resolve({ courseId: 'platform-alias', materialId: 'resource' }),
    };
    expect((await materials.PATCH(request({ active: false }), params)).status).toBe(200);
    expect(course.materials[0].classVisible).toBe(false);
    expect(course.materials[0].classPublicationId).toBeUndefined();
    expect((await materials.DELETE(request({}), params)).status).toBe(200);
    expect((await materials.GET(request({}), params)).status).toBe(404);
    expect(course.materials).toEqual([]);
    expect(lesson('target').materialIds).toEqual([]);
  });

  it('moves a lesson file and keeps its public URL until withdrawn, then removes it from the new lesson', async () => {
    expect((await move('course-file')).status).toBe(200);
    expect(lesson('source').files).toEqual([]);
    expect(lesson('target').files).toHaveLength(1);
    expect(lesson('target').files![0]).toMatchObject({
      lessonId: 'target',
      content: '目标内容',
      classPublicationId: 'CLS-F-old',
    });
    expect(storage.updateServerCourse).toHaveBeenCalledWith('canonical', expect.any(Function));
    const params = { params: Promise.resolve({ courseId: 'platform-alias', fileId: 'resource' }) };
    expect((await files.GET(request({}), params)).status).toBe(200);
    expect((await files.PATCH(request({ action: 'unpublish' }), params)).status).toBe(200);
    expect((await files.GET(request({}), params)).status).toBe(404);
    expect((await files.DELETE(request({}), params)).status).toBe(200);
    expect(lesson('target').files).toEqual([]);
  });

  it.each(['artifact', 'material', 'course-file'])(
    'treats a move into the current lesson as a no-op: %s',
    async (kind) => {
      const original = structuredClone({ course, artifact });
      expect((await move(kind, 'resource', 'source')).status).toBe(200);
      expect({ course, artifact }).toEqual(original);
      expect(storage.saveCourseArtifact).not.toHaveBeenCalled();
      expect(storage.updateServerCourse).not.toHaveBeenCalled();
    },
  );

  it('rejects conflicting lesson file types without changing either folder', async () => {
    lesson('target').files = [
      { ...lesson('source').files![0], id: 'existing', lessonId: 'target', title: '已有目标' },
    ];
    const original = structuredClone(course);
    expect((await move('course-file')).status).toBe(409);
    expect(course).toEqual(original);
    expect(storage.updateServerCourse).not.toHaveBeenCalled();
  });

  it.each(['artifact', 'material', 'course-file'])(
    'rejects a missing destination without modifying %s',
    async (kind) => {
      expect((await move(kind, 'resource', 'missing')).status).toBe(404);
      expect(storage.saveCourseArtifact).not.toHaveBeenCalled();
      expect(storage.updateServerCourse).not.toHaveBeenCalled();
    },
  );

  it('rejects resources belonging to another course', async () => {
    artifact.courseId = 'other-course';
    expect((await move('artifact')).status).toBe(404);
    expect((await move('material', 'missing')).status).toBe(404);
    expect((await move('course-file', 'missing')).status).toBe(404);
    expect(storage.saveCourseArtifact).not.toHaveBeenCalled();
    expect(storage.updateServerCourse).not.toHaveBeenCalled();
  });

  it.each([
    null,
    {},
    { action: 'move-item' },
    { action: 'move-item', itemKind: 'unknown', itemId: 'resource', targetLessonId: 'target' },
  ])('rejects malformed operations: %j', async (body) => {
    expect((await POST(request(body), context)).status).toBe(400);
    expect(storage.updateServerCourse).not.toHaveBeenCalled();
  });

  it('rejects malformed JSON', async () => {
    expect(
      (
        await POST(
          new NextRequest('http://localhost/api/tree', { method: 'POST', body: '{' }),
          context,
        )
      ).status,
    ).toBe(400);
  });

  it.each([
    { action: 'delete-lesson', lessonId: 'source' },
    { action: 'delete-module', moduleId: 'module-a' },
  ])('cleans up artifacts when deleting a folder through a platform alias: %j', async (body) => {
    artifact.classPublicationId = undefined;
    lesson('source').files![0].classPublicationId = undefined;
    expect((await POST(request(body), context)).status).toBe(200);
    expect(storage.listCourseArtifacts).toHaveBeenCalledWith('canonical');
    expect(storage.updateServerCourse).toHaveBeenCalledWith('canonical', expect.any(Function));
    expect(storage.deleteCourseArtifact).toHaveBeenCalledWith('resource');
    expect(course.modules.flatMap((module) => module.lessons).map((item) => item.id)).toEqual([
      'target',
    ]);
  });
});
