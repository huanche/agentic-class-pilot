import { describe, expect, it } from 'vitest';
import { summarizeCourseProgress } from '@/lib/course-space/course-progress';
import type { CourseSpace, CourseArtifactRecord } from '@/lib/course-space';
const course = (): CourseSpace => ({
  id: 'c',
  teacherId: 't',
  title: '课程',
  status: 'active',
  materials: [],
  modules: [],
  createdAt: 1,
  updatedAt: 1,
});
describe('course progress projection', () => {
  it('does not report progress without lesson evidence', () => {
    const result = summarizeCourseProgress(course(), []);
    expect(result.percent).toBe(0);
    expect(result.lessonTotal).toBe(0);
    expect(result.todos.some((item) => item.title.includes('建立周次'))).toBe(true);
  });
  it('counts a prepared lesson only after all three teaching documents are reviewed', () => {
    const c = course();
    c.modules = [
      {
        id: 'm',
        courseId: 'c',
        title: '周次',
        order: 1,
        objectives: [],
        createdAt: 1,
        updatedAt: 1,
        lessons: [
          {
            id: 'l',
            moduleId: 'm',
            title: '第1次课',
            order: 1,
            objectives: [],
            materialIds: [],
            createdAt: 1,
            updatedAt: 1,
            files: ['lesson-objectives', 'knowledge-points'].map((type, i) => ({
              id: 'f' + i,
              lessonId: 'l',
              type: type as 'lesson-objectives' | 'knowledge-points',
              title: type,
              content: '内容',
              status: 'ready',
              createdAt: 1,
              updatedAt: 1,
            })),
          },
        ],
      },
    ];
    const artifact = {
      id: 'a',
      type: 'lesson-courseware',
      scope: { type: 'lesson', lessonId: 'l' },
      status: 'review',
      updatedAt: 1,
    } as CourseArtifactRecord;
    expect(summarizeCourseProgress(c, [artifact]).prepared).toBe(0);
    artifact.status = 'approved';
    expect(summarizeCourseProgress(c, [artifact]).prepared).toBe(1);
    artifact.status = 'published';
    artifact.classVisible = true;
    artifact.classPublicationId = 'CLS-1';
    expect(summarizeCourseProgress(c, [artifact]).published).toBe(0);
    artifact.publicationPlacement = {
      lessonId: 'l',
      week: 1,
      lessonNumber: 1,
      teachingHours: 2,
      resourceType: 'courseware',
      confirmedAt: 1,
    };
    expect(summarizeCourseProgress(c, [artifact]).published).toBe(1);
  });
  it('excludes uploaded outlines from source material progress and flags parsing failures', () => {
    const c = course();
    c.materials = [
      { id: 'a', name: '教材', purpose: 'course-material', status: 'failed' },
      { id: 'b', name: '大纲', purpose: 'course-outline', status: 'ready' },
    ] as CourseSpace['materials'];
    const result = summarizeCourseProgress(c, []);
    expect(result.materialTotal).toBe(1);
    expect(result.materialReady).toBe(0);
    expect(result.todos[0].title).toContain('重试解析');
  });
});
