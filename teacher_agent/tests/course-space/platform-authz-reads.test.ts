import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

const mocks = vi.hoisted(() => ({
  isCourseDatabaseConfigured: vi.fn(),
  readClassroomBindingFromDatabase: vi.fn(),
  readServerCourse: vi.fn(),
  listStoredCourseArtifacts: vi.fn(),
  readCourseJob: vi.fn(),
  readCourseKnowledgeExtractionJob: vi.fn(),
}));
vi.mock('@/lib/server/course-space-database', () => ({
  isCourseDatabaseConfigured: mocks.isCourseDatabaseConfigured,
  readClassroomBindingFromDatabase: mocks.readClassroomBindingFromDatabase,
}));
vi.mock('@/lib/server/course-space-storage', () => ({
  readServerCourse: mocks.readServerCourse,
  listStoredCourseArtifacts: mocks.listStoredCourseArtifacts,
  readCourseJob: mocks.readCourseJob,
}));
vi.mock('@/lib/server/course-knowledge-store', () => ({
  readCourseKnowledgeExtractionJob: mocks.readCourseKnowledgeExtractionJob,
}));

import { GET as classroomVisibility } from '@/app/api/internal/platform/classrooms/[classroomId]/visibility/route';
import { GET as materialVisibility } from '@/app/api/internal/platform/courses/[courseId]/materials/[materialId]/visibility/route';
import { GET as jobCourseRef } from '@/app/api/internal/platform/course-space/jobs/[jobId]/course-ref/route';

const delegated = { headers: { 'x-platform-delegated': 'true' } };

beforeEach(() => {
  vi.resetAllMocks();
  vi.stubEnv('PLATFORM_AUTH_ENABLED', 'true');
  mocks.isCourseDatabaseConfigured.mockReturnValue(true);
});

describe('classroom visibility', () => {
  const context = { params: Promise.resolve({ classroomId: 'room-1' }) };
  const request = () => new NextRequest('http://localhost/api/internal/platform/classrooms/room-1/visibility', delegated);

  it('requires authenticated service delegation', async () => {
    const response = await classroomVisibility(
      new NextRequest('http://localhost/x', {}), context);
    expect(response.status).toBe(403);
    expect(mocks.readClassroomBindingFromDatabase).not.toHaveBeenCalled();
  });

  it('reports detached classrooms as unmapped and unpublished', async () => {
    mocks.readClassroomBindingFromDatabase.mockResolvedValue(null);
    expect(await (await classroomVisibility(request(), context)).json())
      .toEqual({ courseId: null, published: false });
  });

  it('keeps the mapping for inactive courses but denies the student verdict', async () => {
    mocks.readClassroomBindingFromDatabase.mockResolvedValue({ courseId: 'c1', artifactId: 'a1' });
    mocks.readServerCourse.mockResolvedValue({ id: 'c1', status: 'archived' });
    expect(await (await classroomVisibility(request(), context)).json())
      .toEqual({ courseId: 'c1', published: false });
    expect(mocks.listStoredCourseArtifacts).not.toHaveBeenCalled();
  });

  it('publishes only when a visible published artifact references the classroom', async () => {
    mocks.readClassroomBindingFromDatabase.mockResolvedValue({ courseId: 'c1', artifactId: 'a1' });
    mocks.readServerCourse.mockResolvedValue({ id: 'c1', status: 'active' });
    mocks.listStoredCourseArtifacts.mockResolvedValue([
      { status: 'published', classVisible: true, classPublicationId: 'p1', classroomId: 'room-other' },
      { status: 'published', classVisible: true, classPublicationId: 'p2', classroomId: 'room-1' },
    ]);
    expect(await (await classroomVisibility(request(), context)).json())
      .toEqual({ courseId: 'c1', published: true });
  });
});

describe('material visibility', () => {
  const context = { params: Promise.resolve({ courseId: 'c1', materialId: 'm1' }) };
  const request = () => new NextRequest('http://localhost/x', delegated);

  it('reports false for inactive or missing courses', async () => {
    mocks.readServerCourse.mockResolvedValue({ id: 'c1', status: 'archived', materials: [] });
    expect(await (await materialVisibility(request(), context)).json()).toEqual({ visible: false });
    mocks.readServerCourse.mockResolvedValue(null);
    expect(await (await materialVisibility(request(), context)).json()).toEqual({ visible: false });
  });

  it('requires classVisible and a publication id', async () => {
    mocks.readServerCourse.mockResolvedValue({ id: 'c1', status: 'active', materials: [
      { id: 'm1', classVisible: true, classPublicationId: undefined },
      { id: 'm2', classVisible: true, classPublicationId: 'p2' },
    ] });
    expect(await (await materialVisibility(request(), context)).json()).toEqual({ visible: false });
    const other = { params: Promise.resolve({ courseId: 'c1', materialId: 'm2' }) };
    expect(await (await materialVisibility(request(), other)).json()).toEqual({ visible: true });
  });
});

describe('job course resolution', () => {
  const context = { params: Promise.resolve({ jobId: 'job-1' }) };
  const request = (kind?: string) => new NextRequest(
    `http://localhost/x${kind ? `?kind=${kind}` : ''}`, delegated);

  it('resolves artifact jobs by default and graph jobs by kind', async () => {
    mocks.readCourseJob.mockResolvedValue({ courseId: 'c-artifact' });
    mocks.readCourseKnowledgeExtractionJob.mockResolvedValue({ courseId: 'c-graph' });
    expect(await (await jobCourseRef(request(), context)).json()).toEqual({ courseId: 'c-artifact' });
    expect(await (await jobCourseRef(request('graph'), context)).json()).toEqual({ courseId: 'c-graph' });
    expect(mocks.readCourseJob).toHaveBeenCalledWith('job-1');
    expect(mocks.readCourseKnowledgeExtractionJob).toHaveBeenCalledWith('job-1');
  });

  it('returns 404 for unknown jobs', async () => {
    mocks.readCourseJob.mockResolvedValue(null);
    expect((await jobCourseRef(request(), context)).status).toBe(404);
  });
});
