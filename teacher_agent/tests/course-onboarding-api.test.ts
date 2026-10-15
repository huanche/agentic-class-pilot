import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';
const db = vi.hoisted(() => ({ course: null as any, artifacts: [] as any[], sync: vi.fn() }));
vi.mock('@/lib/server/platform-course-bridge', () => ({ registerCourseWithPlatform: db.sync }));
vi.mock('@/lib/server/course-space-storage', () => ({
  readServerCourse: async () => db.course,
  listCourseArtifacts: async () => db.artifacts,
  updateServerCourse: async (_: string, fn: any) => {
    db.course = fn(db.course);
    return db.course;
  },
  readMaterialExtraction: vi.fn(),
  saveCourseArtifact: vi.fn(),
}));
import { POST } from '@/app/api/course-space/[courseId]/setup/route';
const send = (body: object) =>
  POST(
    new NextRequest('http://localhost/api/course-space/c/setup', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
    { params: Promise.resolve({ courseId: 'c' }) },
  );
const schedule = {
  title: '课程新名称',
  totalWeeks: 2,
  lessonsPerWeek: 2,
  teachingHoursPerLesson: 2,
  hasLab: false,
};
describe('onboarding completion gates', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    db.sync.mockResolvedValue(undefined);
    db.course = {
      id: 'c',
      teacherId: 't',
      title: '课程',
      status: 'draft',
      modules: [],
      materials: [{ id: 'source', status: 'ready', purpose: 'course-material' }],
      onboarding: { version: 1, step: 2 },
      createdAt: 1,
      updatedAt: 1,
    };
    db.artifacts = [{ id: 'outline', type: 'course-outline', status: 'review' }];
  });
  it('blocks the next step until every uploaded course source is parsed', async () => {
    db.course.materials.push({ id: 'pending', status: 'parsing' });
    expect((await send({ action: 'advance', step: 2 })).status).toBe(409);
  });
  it('does not complete a course with an unreviewed outline', async () => {
    expect(
      (await send({ action: 'complete', outlineArtifactId: 'outline', schedule })).status,
    ).toBe(409);
    expect(db.course.modules).toHaveLength(0);
  });
  it('persists completion and syncs the confirmed basic course information', async () => {
    db.artifacts[0].status = 'approved';
    expect(
      (await send({ action: 'complete', outlineArtifactId: 'outline', schedule })).status,
    ).toBe(200);
    expect(db.course.onboarding.completedAt).toBeTruthy();
    expect(db.sync).toHaveBeenCalledWith(expect.objectContaining({ title: '课程新名称' }));
  });
  it('keeps the final step resumable if platform synchronization fails', async () => {
    db.artifacts[0].status = 'approved';
    db.sync.mockRejectedValueOnce(new Error('offline'));
    expect(
      (await send({ action: 'complete', outlineArtifactId: 'outline', schedule })).status,
    ).toBe(409);
    expect(db.course.onboarding.completedAt).toBeUndefined();
    expect(db.course.modules).toHaveLength(2);
    expect(
      (await send({ action: 'complete', outlineArtifactId: 'outline', schedule })).status,
    ).toBe(200);
    expect(db.course.modules).toHaveLength(2);
  });
});
