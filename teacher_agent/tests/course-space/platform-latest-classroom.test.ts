import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

const storage = vi.hoisted(() => ({
  readServerCourse: vi.fn(),
  listStoredCourseArtifacts: vi.fn(),
  readClassroom: vi.fn(),
  isCourseDatabaseConfigured: vi.fn(),
  latestPublishedClassroomIdFromDatabase: vi.fn(),
}));
vi.mock('@/lib/server/course-space-storage', () => ({
  readServerCourse: storage.readServerCourse,
  listStoredCourseArtifacts: storage.listStoredCourseArtifacts,
}));
vi.mock('@/lib/server/classroom-storage', () => ({ readClassroom: storage.readClassroom }));
vi.mock('@/lib/server/course-space-database', () => ({
  isCourseDatabaseConfigured: storage.isCourseDatabaseConfigured,
  latestPublishedClassroomIdFromDatabase: storage.latestPublishedClassroomIdFromDatabase,
}));

import { GET } from '@/app/api/internal/platform/courses/[courseId]/latest-classroom/route';

const context = { params: Promise.resolve({ courseId: 'legacy-course-id' }) };
const request = (delegated = true) => new NextRequest(
  'http://localhost/api/internal/platform/courses/legacy-course-id/latest-classroom',
  { headers: delegated ? { 'x-platform-delegated': 'true' } : {} },
);

beforeEach(() => {
  vi.resetAllMocks();
  vi.stubEnv('PLATFORM_AUTH_ENABLED', 'true');
  storage.readServerCourse.mockResolvedValue({ id: 'canonical-id', status: 'active' });
  storage.readClassroom.mockResolvedValue({ id: 'room-older' });
  storage.isCourseDatabaseConfigured.mockReturnValue(false);
});

describe('platform latest published classroom', () => {
  it('requires authenticated service delegation', async () => {
    expect((await GET(request(false), context)).status).toBe(403);
    expect(storage.readServerCourse).not.toHaveBeenCalled();
  });

  it('returns null when the course is inactive', async () => {
    storage.readServerCourse.mockResolvedValue({ id: 'canonical-id', status: 'archived' });
    expect(await (await GET(request(), context)).json()).toEqual({ classroomId: null });
    expect(storage.listStoredCourseArtifacts).not.toHaveBeenCalled();
  });

  it('ignores withdrawn, hidden, and missing classrooms, then selects the newest published one', async () => {
    storage.listStoredCourseArtifacts.mockResolvedValue([
      { status: 'published', classVisible: true, classPublicationId: 'p4',
        classroomId: 'missing', classPublishedAt: 400 },
      { status: 'published', classVisible: false, classPublicationId: 'p3',
        classroomId: 'hidden', classPublishedAt: 300 },
      { status: 'published', classVisible: true, classPublicationId: undefined,
        classroomId: 'withdrawn', classPublishedAt: 250 },
      { status: 'published', classVisible: true, classPublicationId: 'p2',
        classroomId: 'room-older', classPublishedAt: 200 },
    ]);
    storage.readClassroom.mockResolvedValueOnce(null).mockResolvedValueOnce({ id: 'room-older' });
    expect(await (await GET(request(), context)).json()).toEqual({ classroomId: 'room-older' });
    expect(storage.listStoredCourseArtifacts).toHaveBeenCalledWith('canonical-id');
    expect(storage.readClassroom.mock.calls.map(([id]) => id)).toEqual(['missing', 'room-older']);
  });

  it('reads only the classroom id in database mode', async () => {
    storage.isCourseDatabaseConfigured.mockReturnValue(true);
    storage.latestPublishedClassroomIdFromDatabase.mockResolvedValue('room-new');
    expect(await (await GET(request(), context)).json()).toEqual({ classroomId: 'room-new' });
    expect(storage.latestPublishedClassroomIdFromDatabase).toHaveBeenCalledWith('canonical-id');
    expect(storage.listStoredCourseArtifacts).not.toHaveBeenCalled();
    expect(storage.readClassroom).not.toHaveBeenCalled();
  });
});
