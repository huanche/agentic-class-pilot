import { beforeEach, describe, expect, it, vi } from 'vitest';
const db = vi.hoisted(() => ({
  course: null as any,
  artifacts: {} as Record<string, any>,
  read: vi.fn(),
  update: vi.fn(),
  save: vi.fn(),
}));
vi.mock('@/lib/server/course-space-storage', () => ({
  withCourseArtifactLock: async (_id: string, operation: () => Promise<unknown>) => operation(),
  readServerCourse: async () => db.course,
  readCourseArtifact: async (id: string) => db.artifacts[id],
  updateServerCourse: async (_: string, fn: any) => {
    db.course = await fn(db.course);
    return db.course;
  },
  saveCourseArtifact: async (item: any) => {
    db.save(item);
    db.artifacts[item.id] = item;
    return item;
  },
  updateCourseJobIfPresent: vi.fn(),
}));
import { publishCourseResource } from '@/lib/server/course-resource-publication';
const placement = (lessonId: string, week: number) => ({
  lessonId,
  week,
  lessonNumber: 1,
  teachingHours: 2,
  resourceType: 'courseware' as const,
});
describe('explicit course publication binding', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    db.course = {
      id: 'c',
      status: 'active',
      materials: [],
      modules: [
        {
          id: 'm',
          lessons: ['l1', 'l2'].map((id, i) => ({
            id,
            title: `第${i + 1}周`,
            order: i + 1,
            materialIds: [],
            files: [],
          })),
        },
      ],
    };
    db.artifacts = Object.fromEntries(
      ['a1', 'a2'].map((id, i) => [
        id,
        {
          id,
          courseId: 'c',
          type: 'lesson-courseware',
          classroomId: `video-${i + 1}`,
          scope: { type: 'course' },
          status: 'review',
        },
      ]),
    );
  });
  it('rejects publication without a confirmed target', async () => {
    await expect(publishCourseResource('c', 'artifact', 'a1', undefined as any)).rejects.toThrow(
      '请确认',
    );
    expect(db.save).not.toHaveBeenCalled();
  });
  it('stores independent classroom mappings for two lessons', async () => {
    const one = await publishCourseResource('c', 'artifact', 'a1', placement('l1', 1));
    const two = await publishCourseResource('c', 'artifact', 'a2', placement('l2', 2));
    expect(one).toMatchObject({
      classroomId: 'video-1',
      scope: { type: 'lesson', lessonId: 'l1' },
      publicationPlacement: { week: 1, teachingHours: 2 },
    });
    expect(two).toMatchObject({
      classroomId: 'video-2',
      scope: { type: 'lesson', lessonId: 'l2' },
      publicationPlacement: { week: 2 },
    });
    expect(db.course.modules[0].lessons[1]).toMatchObject({
      week: 2,
      lessonNumber: 1,
      teachingHours: 2,
    });
  });
  it('rejects a lesson belonging to another course', async () => {
    await expect(
      publishCourseResource('c', 'artifact', 'a1', placement('foreign', 1)),
    ).rejects.toThrow('不属于');
  });
  it('creates a lesson before publishing an otherwise unassigned resource', async () => {
    const item = await publishCourseResource('c', 'artifact', 'a1', {
      ...placement('', 3),
      newLessonTitle: '第3周第1次课',
    });
    const target = db.course.modules
      .flatMap((m: any) => m.lessons)
      .find((l: any) => l.id === item.publicationPlacement!.lessonId);
    expect(target).toMatchObject({ title: '第3周第1次课', week: 3, teachingHours: 2 });
  });
  it('does not silently reassign a confirmed publication', async () => {
    await publishCourseResource('c', 'artifact', 'a1', placement('l1', 1));
    await expect(publishCourseResource('c', 'artifact', 'a1', placement('l2', 2))).rejects.toThrow(
      '不能更改归属',
    );
  });
  it('keeps a publication id when repairing legacy unassigned content', async () => {
    db.artifacts.a1.classPublicationId = 'CLS-legacy';
    const item = await publishCourseResource('c', 'artifact', 'a1', placement('l1', 1));
    expect(item.classPublicationId).toBe('CLS-legacy');
  });
});
