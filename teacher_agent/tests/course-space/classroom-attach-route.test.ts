import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

const storage = vi.hoisted(() => ({
  readServerCourse: vi.fn(),
  listCourseArtifacts: vi.fn(),
  saveCourseArtifact: vi.fn(),
  updateServerCourse: vi.fn(),
  readClassroom: vi.fn(),
  persistClassroom: vi.fn(),
  buildRequestOrigin: vi.fn(() => 'http://localhost:8088'),
}));
vi.mock('@/lib/server/course-space-storage', () => ({
  readServerCourse: storage.readServerCourse,
  listCourseArtifacts: storage.listCourseArtifacts,
  saveCourseArtifact: storage.saveCourseArtifact,
  updateServerCourse: storage.updateServerCourse,
}));
vi.mock('@/lib/server/classroom-storage', () => ({
  readClassroom: storage.readClassroom,
  persistClassroom: storage.persistClassroom,
  buildRequestOrigin: storage.buildRequestOrigin,
}));
import { POST } from '@/app/api/course-space/[courseId]/classrooms/attach/route';

const context = { params: Promise.resolve({ courseId: 'course-a' }) };
const course = { id: 'course-a', teacherId: 'teacher-a', title: '现代交换原理', modules: [] };
const classroom = {
  id: 'classroom-a',
  stage: { id: 'classroom-a', name: '第一次课' },
  scenes: [{ id: 'scene-a', actions: [] }],
};
function request(scope = { type: 'course' }) {
  return new NextRequest('http://localhost:8088/api/course-space/course-a/classrooms/attach', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      classroomId: classroom.id,
      scope,
      stage: classroom.stage,
      scenes: classroom.scenes,
    }),
  });
}

describe('course-scoped classroom attachment', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    storage.readServerCourse.mockResolvedValue(course);
    storage.listCourseArtifacts.mockResolvedValue([]);
    storage.readClassroom.mockResolvedValueOnce(null).mockResolvedValueOnce(classroom);
    storage.saveCourseArtifact.mockImplementation(async (artifact) => artifact);
    storage.buildRequestOrigin.mockReturnValue('http://localhost:8088');
  });

  it('persists OpenMAIC scenes before indexing the review artifact', async () => {
    const response = await POST(request(), context);
    expect(response.status).toBe(200);
    expect(storage.persistClassroom).toHaveBeenCalledWith(classroom, 'http://localhost:8088');
    expect(storage.saveCourseArtifact).toHaveBeenCalledWith(
      expect.objectContaining({
        classroomId: classroom.id,
        status: 'review',
        type: 'lesson-courseware',
      }),
    );
  });

  it('rejects a scope outside the course before saving classroom scenes', async () => {
    const response = await POST(request({ type: 'module', moduleId: 'other' } as never), context);
    expect(response.status).toBe(400);
    expect(storage.persistClassroom).not.toHaveBeenCalled();
  });
});
