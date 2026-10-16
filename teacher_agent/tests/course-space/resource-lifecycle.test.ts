import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';
import type { CourseSpace } from '@/lib/course-space/types';

const storage = vi.hoisted(() => ({
  readServerCourse: vi.fn(),
  updateServerCourse: vi.fn(),
  readCourseMaterialBytes: vi.fn(),
  readCourseArtifact: vi.fn(),
  saveCourseArtifact: vi.fn(),
  updateCourseJobIfPresent: vi.fn(),
}));
vi.mock('@/lib/server/course-space-storage', () => storage);
import * as materials from '@/app/api/course-space/[courseId]/materials/[materialId]/route';
import * as files from '@/app/api/course-space/[courseId]/lesson-files/[fileId]/route';

let course: CourseSpace;
const materialContext = {
  params: Promise.resolve({ courseId: 'platform-alias', materialId: 'material-a' }),
};
const fileContext = { params: Promise.resolve({ courseId: 'platform-alias', fileId: 'file-a' }) };
const request = (body: unknown) =>
  new NextRequest('http://localhost/api/resource', { method: 'PATCH', body: JSON.stringify(body) });
const placement = {
  lessonId: 'lesson-a',
  week: 1,
  lessonNumber: 1,
  teachingHours: 2,
  resourceType: 'material',
};

beforeEach(() => {
  vi.resetAllMocks();
  course = {
    id: 'canonical',
    status: 'active',
    materials: [
      { id: 'material-a', status: 'ready', classVisible: true, classPublicationId: 'CLS-M-old' },
    ],
    modules: [
      {
        id: 'module-a',
        lessons: [
          {
            id: 'lesson-a',
            materialIds: ['material-a'],
            files: [
              {
                id: 'file-a',
                title: '课程目标',
                content: 'test',
                status: 'ready',
                classVisible: true,
                classPublicationId: 'CLS-F-old',
              },
            ],
          },
        ],
      },
    ],
  } as CourseSpace;
  storage.readServerCourse.mockImplementation(async () => course);
  storage.updateServerCourse.mockImplementation(
    async (_id, update) => (course = await update(course)),
  );
});

describe('resource publication lifecycle', () => {
  it('withdraws material and permits a new publication', async () => {
    expect((await materials.PATCH(request({ active: false }), materialContext)).status).toBe(200);
    expect(course.materials[0].classVisible).toBe(false);
    expect(course.materials[0].classPublicationId).toBeUndefined();
    expect(
      (await materials.PATCH(request({ active: true, placement }), materialContext)).status,
    ).toBe(200);
    expect(course.materials[0].classPublicationId).toMatch(/^CLS-M-/);
    expect(course.materials[0].classPublicationId).not.toBe('CLS-M-old');
  });
  it('deletes material and removes all lesson references', async () => {
    expect((await materials.DELETE(request({}), materialContext)).status).toBe(200);
    expect(course.materials).toEqual([]);
    expect(course.modules[0].lessons[0].materialIds).toEqual([]);
    expect((await materials.GET(request({}), materialContext)).status).toBe(404);
  });
  it('withdraws a lesson file and revokes its old public URL', async () => {
    expect((await files.PATCH(request({ action: 'unpublish' }), fileContext)).status).toBe(200);
    expect(course.modules[0].lessons[0].files?.[0].classVisible).toBe(false);
    expect((await files.GET(request({}), fileContext)).status).toBe(404);
    expect(
      (
        await files.PATCH(
          request({ action: 'publish', placement: { ...placement, resourceType: 'objectives' } }),
          fileContext,
        )
      ).status,
    ).toBe(200);
    expect((await files.GET(request({}), fileContext)).status).toBe(200);
  });
  it('deletes only the requested lesson file', async () => {
    expect((await files.DELETE(request({}), fileContext)).status).toBe(200);
    expect(course.modules[0].lessons[0].files).toEqual([]);
    expect(course.materials).toHaveLength(1);
  });
  it('rejects invalid operations instead of accidentally withdrawing', async () => {
    expect((await materials.PATCH(request({}), materialContext)).status).toBe(400);
    expect((await files.PATCH(request({ action: 'unknown' }), fileContext)).status).toBe(400);
    expect(storage.updateServerCourse).not.toHaveBeenCalled();
  });
});
