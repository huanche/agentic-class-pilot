import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

const mocks = vi.hoisted(() => ({
  readClassroom: vi.fn(),
  readCourseArtifact: vi.fn(),
}));
vi.mock('@/lib/server/classroom-storage', () => ({ readClassroom: mocks.readClassroom }));
vi.mock('@/lib/server/course-space-storage', () => ({ readCourseArtifact: mocks.readCourseArtifact }));

import { GET as classroomContent } from '@/app/api/internal/platform/classrooms/[classroomId]/content/route';
import { GET as publishedLesson } from '@/app/api/internal/platform/artifacts/[artifactId]/published-lesson/route';

const delegated = { headers: { 'x-platform-delegated': 'true' } };
const classroom = {
  id: 'room-1', stage: { name: '课堂名' },
  scenes: [{ id: 's1', type: 'slide', order: 1, title: '第一页',
    content: { canvas: { elements: [{ type: 'text', content: '要点一' }] } }, actions: [] }],
};

beforeEach(() => {
  vi.resetAllMocks();
  vi.stubEnv('PLATFORM_AUTH_ENABLED', 'true');
});

describe('classroom content projection', () => {
  const context = { params: Promise.resolve({ classroomId: 'room-1' }) };
  const request = () => new NextRequest('http://localhost/x', delegated as RequestInit);

  it('requires authenticated service delegation', async () => {
    const response = await classroomContent(
      new NextRequest('http://localhost/x', {} as RequestInit), context);
    expect(response.status).toBe(403);
    expect(mocks.readClassroom).not.toHaveBeenCalled();
  });

  it('returns null classroom when the snapshot is missing', async () => {
    mocks.readClassroom.mockResolvedValue(null);
    expect(await (await classroomContent(request(), context)).json()).toEqual({ classroom: null });
  });

  it('projects scenes with visible text, mirroring the platform view', async () => {
    mocks.readClassroom.mockResolvedValue(classroom);
    const body = await (await classroomContent(request(), context)).json();
    expect(body.classroom).toMatchObject({ id: 'room-1', title: '课堂名' });
    expect(body.classroom.scenes[0].visibleText).toEqual(['要点一']);
    expect(body.classroom.scenes[0]).not.toHaveProperty('content');
  });
});

describe('published lesson verdict', () => {
  const context = { params: Promise.resolve({ artifactId: 'a1' }) };
  const request = () => new NextRequest('http://localhost/x', delegated as RequestInit);

  it('rejects unpublished artifacts with the not-published reason', async () => {
    mocks.readCourseArtifact.mockResolvedValue({ status: 'approved', classVisible: true });
    expect(await (await publishedLesson(request(), context)).json()).toEqual({
      published: false, reason: 'not-published', lesson: null });
  });

  it('rejects published artifacts that are not lesson videos', async () => {
    mocks.readCourseArtifact.mockResolvedValue({
      status: 'published', classVisible: true, classPublicationId: 'p1',
      publicationPlacement: {}, classroomId: undefined,
    });
    expect(await (await publishedLesson(request(), context)).json()).toEqual({
      published: false, reason: 'not-a-lesson-video', lesson: null });
  });

  it('maps a missing snapshot to the classroom-missing reason', async () => {
    mocks.readCourseArtifact.mockResolvedValue({
      status: 'published', classVisible: true, classPublicationId: 'p1',
      publicationPlacement: { lessonId: 'L1' }, classroomId: 'room-1',
      classPublishedAt: 300, courseId: 'c1',
    });
    mocks.readClassroom.mockResolvedValue(null);
    expect(await (await publishedLesson(request(), context)).json()).toEqual({
      published: false, reason: 'classroom-missing', lesson: null });
  });

  it('returns the lesson with the projected classroom', async () => {
    mocks.readCourseArtifact.mockResolvedValue({
      status: 'published', classVisible: true, classPublicationId: 'p1',
      publicationPlacement: { lessonId: 'L1' }, classroomId: 'room-1',
      classPublishedAt: 300, courseId: 'c1',
    });
    mocks.readClassroom.mockResolvedValue(classroom);
    const body = await (await publishedLesson(request(), context)).json();
    expect(body.published).toBe(true);
    expect(body.reason).toBeNull();
    expect(body.lesson).toMatchObject({
      courseId: 'c1', lessonId: 'L1', classroomId: 'room-1', publishedAt: 300 });
    expect(body.lesson.classroom.scenes[0].visibleText).toEqual(['要点一']);
  });
});
