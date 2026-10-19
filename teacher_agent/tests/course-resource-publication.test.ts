import { beforeEach, describe, expect, it, vi } from 'vitest';
import type {
  CourseSpace,
  CourseArtifactRecord,
  PublishedKnowledgePackage,
} from '@/lib/course-space/types';
import type { PublicationRequest } from '@/lib/server/course-resource-publication';
const db = vi.hoisted(() => ({
  course: undefined as unknown as CourseSpace,
  artifacts: {} as Record<string, CourseArtifactRecord>,
  read: vi.fn(),
  update: vi.fn(),
  save: vi.fn(),
  packageSave: vi.fn(),
  packages: [] as PublishedKnowledgePackage[],
}));
vi.mock('@/lib/server/course-space-storage', () => ({
  readServerCourse: async () => db.course,
  readCourseArtifact: async (id: string) => db.artifacts[id],
  updateServerCourse: async (
    _: string,
    fn: (course: CourseSpace) => CourseSpace | Promise<CourseSpace>,
  ) => {
    db.course = await fn(db.course);
    return db.course;
  },
  saveCourseArtifact: async (item: CourseArtifactRecord) => {
    db.save(item);
    db.artifacts[item.id] = item;
    return item;
  },
  updateCourseJobIfPresent: vi.fn(),
  listCourseArtifacts: async () => Object.values(db.artifacts),
  listKnowledgePackages: async () => db.packages,
  saveKnowledgePackage: async (item: PublishedKnowledgePackage) => {
    await db.packageSave(item);
    db.packages = [...db.packages.filter((pkg) => pkg.id !== item.id), item];
    return item;
  },
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
    db.packages = [];
    db.packageSave.mockReset();
    db.course = {
      id: 'c',
      teacherId: 't',
      title: '本地课程',
      createdAt: 1,
      updatedAt: 1,
      status: 'active',
      materials: [],
      modules: [
        {
          id: 'm',
          courseId: 'c',
          title: '模块',
          order: 1,
          objectives: [],
          createdAt: 1,
          updatedAt: 1,
          lessons: ['l1', 'l2'].map((id, i) => ({
            id,
            moduleId: 'm',
            objectives: [],
            createdAt: 1,
            updatedAt: 1,
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
          jobId: `j${i}`,
          teacherId: 't',
          createdAt: 1,
          updatedAt: 1,
          type: 'lesson-courseware',
          classroomId: `video-${i + 1}`,
          scope: { type: 'course' },
          status: 'review',
          title: `课件${i + 1}`,
          content: `讲解${i + 1}`,
          citations: [],
        },
      ]),
    );
  });
  it('rejects publication without a confirmed target', async () => {
    await expect(
      publishCourseResource('c', 'artifact', 'a1', undefined as unknown as PublicationRequest),
    ).rejects.toThrow('请确认');
    expect(db.save).not.toHaveBeenCalled();
  });
  it('publishes a draft courseware and initializes the student package in one operation', async () => {
    db.course.status = 'draft';
    const published = await publishCourseResource('c', 'artifact', 'a1', placement('l1', 1));
    expect(published.status).toBe('published');
    expect(published).toMatchObject({ approvedAt: expect.any(Number) });
    expect(db.course.status).toBe('active');
    expect(db.course.activeKnowledgePackageId).toBe(db.packages[0].id);
    expect(db.packages[0].entries.map((entry) => entry.content)).toEqual(['讲解1']);
    expect(db.artifacts.a2.status).toBe('review');
    expect(db.artifacts.a2.classVisible).toBeUndefined();
  });
  it('does not initialize a course for an invalid publication', async () => {
    db.course.status = 'draft';
    await expect(
      publishCourseResource('c', 'artifact', 'a1', placement('foreign', 1)),
    ).rejects.toThrow('不属于');
    expect(db.course.status).toBe('draft');
    expect(db.packageSave).not.toHaveBeenCalled();
    expect(db.save).not.toHaveBeenCalled();
  });
  it('rejects archived courses without changing their resources', async () => {
    db.course.status = 'archived';
    await expect(publishCourseResource('c', 'artifact', 'a1', placement('l1', 1))).rejects.toThrow(
      '归档',
    );
    expect(db.save).not.toHaveBeenCalled();
  });
  it('retries failed package initialization without duplicating the publication', async () => {
    db.course.status = 'draft';
    db.packageSave.mockRejectedValueOnce(new Error('storage unavailable'));
    await expect(publishCourseResource('c', 'artifact', 'a1', placement('l1', 1))).rejects.toThrow(
      'storage unavailable',
    );
    const publicationId = db.artifacts.a1.classPublicationId;
    expect(db.course.status).toBe('draft');
    const retried = await publishCourseResource('c', 'artifact', 'a1', placement('l1', 1));
    expect(retried.classPublicationId).toBe(publicationId);
    expect(db.save).toHaveBeenCalledTimes(1);
    expect(db.course.status).toBe('active');
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
      .flatMap((m) => m.lessons)
      .find((l) => l.id === item.publicationPlacement!.lessonId);
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
