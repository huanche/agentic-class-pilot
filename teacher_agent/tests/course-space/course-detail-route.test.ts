import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

const storage = vi.hoisted(() => ({
  readServerCourse: vi.fn(),
  saveServerCourse: vi.fn(),
  listCourseJobs: vi.fn(),
  listCourseArtifacts: vi.fn(),
}));
vi.mock('@/lib/server/course-space-storage', () => storage);
import { GET, PUT } from '@/app/api/course-space/[courseId]/route';

const context = { params: Promise.resolve({ courseId: 'course-a' }) };

function putRequest(body: unknown): NextRequest {
  return new NextRequest('http://localhost/api/course-space/course-a', {
    method: 'PUT',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
}

const existingCourse = {
  id: 'course-a',
  teacherId: 'teacher-001',
  status: 'active',
  activeKnowledgePackageId: 'pkg-v1',
  classStudents: [{ studentId: 's1', name: '学生一', status: 'learning', progress: 40, completedResourceIds: [], lastActiveAt: 1 }],
  title: '已发布课程',
  modules: [],
  materials: [],
  createdAt: 1,
  updatedAt: 2,
};

describe('course detail route', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    storage.saveServerCourse.mockImplementation(async (course) => course);
  });

  it('lists jobs and artifacts under the canonical course id', async () => {
    storage.readServerCourse.mockResolvedValue({ ...existingCourse, id: 'legacyCourse1' });
    storage.listCourseJobs.mockResolvedValue([]);
    storage.listCourseArtifacts.mockResolvedValue([]);
    const response = await GET(new NextRequest('http://localhost/api/course-space/uuid-entry'), {
      params: Promise.resolve({ courseId: 'uuid-entry' }),
    });
    expect(response.status).toBe(200);
    expect(storage.listCourseJobs).toHaveBeenCalledWith('legacyCourse1');
    expect(storage.listCourseArtifacts).toHaveBeenCalledWith('legacyCourse1');
  });

  it('keeps server-owned publication state when a stale client copy is saved', async () => {
    storage.readServerCourse.mockResolvedValue(existingCourse);
    // A long-lived workspace tab that never saw the publish.
    const staleCopy = { ...existingCourse, status: 'draft', activeKnowledgePackageId: undefined, classStudents: undefined };
    const response = await PUT(putRequest(staleCopy), context);
    expect(response.status).toBe(200);
    const saved = storage.saveServerCourse.mock.calls[0][0];
    expect(saved.status).toBe('active');
    expect(saved.activeKnowledgePackageId).toBe('pkg-v1');
    expect(saved.classStudents).toEqual(existingCourse.classStudents);
  });

  it('still accepts structural edits from the stale copy', async () => {
    storage.readServerCourse.mockResolvedValue(existingCourse);
    const edited = { ...existingCourse, title: '改名', modules: [{ id: 'm1' }] };
    const response = await PUT(putRequest(edited), context);
    expect(response.status).toBe(200);
    const saved = storage.saveServerCourse.mock.calls[0][0];
    expect(saved.title).toBe('改名');
    expect(saved.modules).toEqual([{ id: 'm1' }]);
  });

  it('rejects a course id that does not match the canonical id', async () => {
    storage.readServerCourse.mockResolvedValue({ ...existingCourse, id: 'legacyCourse1' });
    const response = await PUT(putRequest({ ...existingCourse, id: 'other-course' }), context);
    expect(response.status).toBe(400);
  });
});
