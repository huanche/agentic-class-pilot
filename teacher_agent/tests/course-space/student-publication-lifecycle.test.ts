import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';
const storage = vi.hoisted(() => ({
  readServerCourse: vi.fn(),
  listCourseArtifacts: vi.fn(),
  readCourseArtifact: vi.fn(),
  readPublishedKnowledgePackage: vi.fn(),
}));
vi.mock('@/lib/server/course-space-storage', () => storage);
vi.mock('@/lib/server/course-space-database', () => ({
  readCourseKnowledgeGraphFromDatabase: vi.fn(),
}));
vi.mock('@/lib/server/student-agent-auth', () => ({ authorizeStudentAgent: vi.fn(() => null) }));
vi.mock('@/lib/server/classroom-storage', () => ({
  readClassroom: vi.fn(async () => ({ stage: { id: 'room-a' }, scenes: [] })),
}));
import { GET as courseDetail } from '@/app/api/student-agent/v1/courses/[courseId]/route';
import { GET as artifactDetail } from '@/app/api/student-agent/v1/courses/[courseId]/artifacts/[artifactId]/route';
import { GET as classroomDetail } from '@/app/api/student-agent/v1/courses/[courseId]/classrooms/[classroomId]/route';

const request = new NextRequest('http://localhost/api/student-agent/v1/courses/alias');
const context = {
  params: Promise.resolve({ courseId: 'alias', artifactId: 'a', classroomId: 'room-a' }),
};
const artifact = {
  id: 'a',
  courseId: 'canonical',
  title: '公开课件',
  content: '公开内容',
  scope: { type: 'course' },
  classroomId: 'room-a',
  status: 'published',
  classVisible: true,
  classPublicationId: 'CLS-A-live',
  citations: [],
};
beforeEach(() => {
  vi.resetAllMocks();
  storage.readServerCourse.mockResolvedValue({
    id: 'canonical',
    title: 'Course',
    status: 'active',
    modules: [
      {
        id: 'module',
        lessons: [
          { id: 'lesson', files: [{ id: 'withdrawn-file', status: 'ready', classVisible: false }] },
        ],
      },
    ],
  });
  storage.readPublishedKnowledgePackage.mockResolvedValue({
    id: 'pkg',
    entries: [{ id: 'old-snapshot', content: '已撤回内容' }],
  });
  storage.listCourseArtifacts.mockResolvedValue([artifact]);
  storage.readCourseArtifact.mockResolvedValue(artifact);
});
describe('student publication lifecycle', () => {
  it('resolves platform aliases and exposes only current publications', async () => {
    const response = await courseDetail(request, context);
    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body.knowledgePackage.entries.map((entry: { id: string }) => entry.id)).toEqual(['a']);
    expect(body.course.modules[0].lessons[0].files).toEqual([]);
    expect(storage.listCourseArtifacts).toHaveBeenCalledWith('canonical');
    expect((await artifactDetail(request, context)).status).toBe(200);
    expect((await classroomDetail(request, context)).status).toBe(200);
  });
  it('revokes direct artifact and classroom reads after withdrawal', async () => {
    const revoked = {
      ...artifact,
      status: 'approved',
      classVisible: false,
      classPublicationId: undefined,
    };
    storage.readCourseArtifact.mockResolvedValue(revoked);
    storage.listCourseArtifacts.mockResolvedValue([revoked]);
    expect((await artifactDetail(request, context)).status).toBe(404);
    expect((await classroomDetail(request, context)).status).toBe(404);
    const body = await (await courseDetail(request, context)).json();
    expect(body.artifacts).toEqual([]);
    expect(body.knowledgePackage.entries).toEqual([]);
  });
  it('does not expose courseware after the course is closed', async () => {
    storage.readServerCourse.mockResolvedValue({ id: 'canonical', status: 'draft' });
    expect((await artifactDetail(request, context)).status).toBe(404);
    expect((await classroomDetail(request, context)).status).toBe(404);
  });
});
