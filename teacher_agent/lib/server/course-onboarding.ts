import { nanoid } from 'nanoid';
import type { CourseSpace } from '@/lib/course-space/types';
export type CourseScheduleInput = {
  title: string;
  subject?: string;
  gradeBand?: string;
  term?: string;
  description?: string;
  totalWeeks: number;
  lessonsPerWeek: number;
  teachingHoursPerLesson: number;
  hasLab: boolean;
};
export function buildOnboardingSchedule(
  course: CourseSpace,
  input: CourseScheduleInput,
): CourseSpace {
  if (!input || typeof input.title !== 'string' || !input.title.trim())
    throw new Error('请填写课程名称');
  if (
    !Number.isInteger(input.totalWeeks) ||
    input.totalWeeks < 1 ||
    input.totalWeeks > 52 ||
    !Number.isInteger(input.lessonsPerWeek) ||
    input.lessonsPerWeek < 1 ||
    input.lessonsPerWeek > 10 ||
    !Number.isFinite(input.teachingHoursPerLesson) ||
    input.teachingHoursPerLesson <= 0 ||
    input.teachingHoursPerLesson > 8 ||
    typeof input.hasLab !== 'boolean'
  )
    throw new Error('请填写有效的上课周数、每周课次、每次课时数和实验课设置');
  if (
    course.modules.some(
      (item) =>
        item.workspaceKind === 'week' &&
        ((item.week ?? 0) > input.totalWeeks ||
          item.lessons.some((lesson) => (lesson.lessonNumber ?? 0) > input.lessonsPerWeek)),
    )
  )
    throw new Error('已有周次或课次超出新安排，请先在工作区核对，系统不会自动删除已有文件');
  if (input.title.trim().length > 255 || (input.description?.length ?? 0) > 2000)
    throw new Error('课程名称最多255字，简介最多2000字');
  const now = Date.now();
  const modules = course.modules.map((item) => ({ ...item, lessons: [...item.lessons] }));
  for (let week = 1; week <= input.totalWeeks; week++) {
    let weekFolder = modules.find((item) => item.workspaceKind === 'week' && item.week === week);
    if (!weekFolder) {
      weekFolder = {
        id: nanoid(12),
        courseId: course.id,
        title: `第${week}周`,
        workspaceKind: 'week',
        week,
        order: modules.length + 1,
        objectives: [],
        lessons: [],
        createdAt: now,
        updatedAt: now,
      };
      modules.push(weekFolder);
    }
    for (let number = 1; number <= input.lessonsPerWeek; number++) {
      if (weekFolder.lessons.some((lesson) => lesson.lessonNumber === number)) continue;
      weekFolder.lessons.push({
        id: nanoid(14),
        moduleId: weekFolder.id,
        title: `第${number}次课`,
        week,
        lessonNumber: number,
        teachingHours: input.teachingHoursPerLesson,
        order: number,
        objectives: [],
        materialIds: [],
        files: [],
        createdAt: now,
        updatedAt: now,
      });
    }
  }
  if (
    input.hasLab &&
    !modules.some((item) => item.workspaceKind === 'experiment' || item.title === '课程实验')
  )
    modules.push({
      id: `folder-${nanoid(12)}`,
      courseId: course.id,
      title: '课程实验',
      workspaceKind: 'experiment',
      order: modules.length + 1,
      objectives: [],
      lessons: [],
      createdAt: now,
      updatedAt: now,
    });
  return {
    ...course,
    title: input.title.trim(),
    subject: input.subject?.trim(),
    gradeBand: input.gradeBand?.trim(),
    term: input.term?.trim(),
    description: input.description?.trim(),
    modules,
    curriculum: {
      ...course.curriculum,
      totalWeeks: input.totalWeeks,
      lessonsPerWeek: input.lessonsPerWeek,
      teachingHoursPerLesson: input.teachingHoursPerLesson,
      hasLab: input.hasLab,
    },
    onboarding: { version: 1, ...course.onboarding, step: 3, completedAt: now },
    updatedAt: now,
  };
}
