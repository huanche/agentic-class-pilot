import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

const storage = vi.hoisted(() => ({
  readServerCourse: vi.fn(),
  listCourseArtifacts: vi.fn(),
  listKnowledgePackages: vi.fn(),
  saveKnowledgePackage: vi.fn(),
  saveCourseArtifact: vi.fn(),
  updateServerCourse: vi.fn(),
}));
vi.mock('@/lib/server/course-space-storage', () => storage);
import { POST as publish } from '@/app/api/course-space/[courseId]/publish/route';
import type { CourseArtifactRecord } from '@/lib/course-space/types';

const baseArtifact = {
  jobId: 'job-1',
  teacherId: 'teacher-001',
  scope: { type: 'course' as const },
  type: 'lesson-courseware',
  title: 'Courseware',
  content: 'content',
  createdAt: 1,
  updatedAt: 1,
};

function artifact(partial: Partial<CourseArtifactRecord>): CourseArtifactRecord {
  return { id: 'artifact-1', status: 'approved', citations: [], ...baseArtifact, ...partial } as CourseArtifactRecord;
}

const request = new NextRequest('http://localhost/api/course-space/course-a/publish', { method: 'POST' });

describe('course publish route', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    storage.saveKnowledgePackage.mockImplementation(async (pkg) => pkg);
    storage.saveCourseArtifact.mockImplementation(async (a) => a);
    storage.updateServerCourse.mockImplementation(async (_id, update) => update({ id: 'course-a', status: 'active' }));
  });

  it('rejects publishing when the course does not exist', async () => {
    storage.readServerCourse.mockResolvedValue(null);
    expect((await publish(request, { params: Promise.resolve({ courseId: 'course-a' }) })).status).toBe(404);
  });

  it('rejects publishing without approved artifacts', async () => {
    storage.readServerCourse.mockResolvedValue({ id: 'course-a', teacherId: 'teacher-001', status: 'draft' });
    storage.listCourseArtifacts.mockResolvedValue([artifact({ status: 'review' })]);
    const response = await publish(request, { params: Promise.resolve({ courseId: 'course-a' }) });
    expect(response.status).toBe(409);
    expect((await response.json()).error).toContain('没有审核通过');
  });

  it('rejects approved text artifacts without citations', async () => {
    storage.readServerCourse.mockResolvedValue({ id: 'course-a', teacherId: 'teacher-001', status: 'draft' });
    storage.listCourseArtifacts.mockResolvedValue([artifact({ classroomId: undefined, citations: [] })]);
    const response = await publish(request, { params: Promise.resolve({ courseId: 'course-a' }) });
    expect(response.status).toBe(409);
    expect((await response.json()).error).toContain('缺少来源引用');
  });

  it('publishes interactive courseware without citations under the canonical course id', async () => {
    // Platform UUID entry point resolving to a legacy course id.
    storage.readServerCourse.mockResolvedValue({ id: 'legacyCourse1', teacherId: 'teacher-001', status: 'draft' });
    storage.listCourseArtifacts.mockResolvedValue([
      artifact({ courseId: 'legacyCourse1', classroomId: 'classroom-1', citations: [] }),
    ]);
    storage.listKnowledgePackages.mockResolvedValue([]);
    const response = await publish(request, { params: Promise.resolve({ courseId: 'uuid-entry' }) });
    expect(response.status).toBe(201);
    const body = await response.json();
    expect(body.knowledgePackage.courseId).toBe('legacyCourse1');
    expect(storage.listCourseArtifacts).toHaveBeenCalledWith('legacyCourse1');
    expect(storage.updateServerCourse).toHaveBeenCalledWith('legacyCourse1', expect.any(Function));
  });

  it('inserts the successor package before superseding the previous one', async () => {
    storage.readServerCourse.mockResolvedValue({ id: 'course-a', teacherId: 'teacher-001', status: 'active' });
    storage.listCourseArtifacts.mockResolvedValue([
      artifact({ courseId: 'course-a', classroomId: 'classroom-1' }),
    ]);
    storage.listKnowledgePackages.mockResolvedValue([
      { id: 'pkg-v1', courseId: 'course-a', version: 1, status: 'published' },
    ]);
    const order: string[] = [];
    storage.saveKnowledgePackage.mockImplementation(async (pkg) => {
      order.push(pkg.status === 'published' ? 'insert' : 'supersede');
      return pkg;
    });
    const response = await publish(request, { params: Promise.resolve({ courseId: 'course-a' }) });
    expect(response.status).toBe(201);
    const body = await response.json();
    expect(body.knowledgePackage.version).toBe(2);
    // An interruption between the two writes must never orphan the course
    // without a published package: insert first, retire second.
    expect(order).toEqual(['insert', 'supersede']);
  });
});
