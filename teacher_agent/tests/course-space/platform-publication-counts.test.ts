import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

const storage = vi.hoisted(() => ({
  readServerCourse: vi.fn(),
  listCourseArtifacts: vi.fn(),
}));
vi.mock('@/lib/server/course-space-storage', () => storage);

import { GET } from '@/app/api/internal/platform/courses/[courseId]/publication-counts/route';

const context = { params: Promise.resolve({ courseId: 'legacy-course-id' }) };
const request = (delegated = true) => new NextRequest(
  'http://localhost/api/internal/platform/courses/legacy-course-id/publication-counts',
  { headers: delegated ? { 'x-platform-delegated': 'true' } : {} },
);

beforeEach(() => {
  vi.resetAllMocks();
  vi.stubEnv('PLATFORM_AUTH_ENABLED', 'true');
  storage.readServerCourse.mockResolvedValue({ id: 'canonical-id', status: 'active' });
  storage.listCourseArtifacts.mockResolvedValue([
    { status: 'published', classroomId: 'room-1' },
    { status: 'published', classroomId: 'room-1' },
    { status: 'published', classroomId: 'room-2' },
    { status: 'draft', classroomId: 'room-3' },
    { status: 'published', classroomId: undefined },
  ]);
});

describe('platform publication counts', () => {
  it('requires middleware-confirmed delegation', async () => {
    expect((await GET(request(false), context)).status).toBe(403);
    expect(storage.readServerCourse).not.toHaveBeenCalled();
  });

  it('preserves distinct classroom and artifact count semantics', async () => {
    const response = await GET(request(), context);
    expect(await response.json()).toEqual({
      distinctClassrooms: 2,
      publishedArtifactsWithClassroom: 3,
    });
    expect(storage.listCourseArtifacts).toHaveBeenCalledWith('canonical-id');
  });
});
