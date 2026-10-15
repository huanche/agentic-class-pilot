import { describe, expect, it } from 'vitest';
import { buildOnboardingSchedule, type CourseScheduleInput } from '@/lib/server/course-onboarding';
import type { CourseSpace } from '@/lib/course-space/types';
const empty: CourseSpace = {
  id: 'c',
  teacherId: 't',
  title: '课程',
  status: 'draft',
  modules: [],
  materials: [],
  createdAt: 1,
  updatedAt: 1,
  onboarding: { version: 1, step: 3, outlineArtifactId: 'outline' },
};
const input: CourseScheduleInput = {
  title: '现代交换原理',
  totalWeeks: 3,
  lessonsPerWeek: 2,
  teachingHoursPerLesson: 2,
  hasLab: true,
};
describe('new course schedule', () => {
  it('creates weekly folders with independently addressable lesson ids and a separate lab folder', () => {
    const result = buildOnboardingSchedule(empty, input);
    const weeks = result.modules.filter((item) => item.workspaceKind === 'week');
    expect(weeks.map((item) => item.title)).toEqual(['第1周', '第2周', '第3周']);
    expect(
      weeks
        .flatMap((item) => item.lessons)
        .map((item) => [item.week, item.lessonNumber, item.teachingHours]),
    ).toEqual([
      [1, 1, 2],
      [1, 2, 2],
      [2, 1, 2],
      [2, 2, 2],
      [3, 1, 2],
      [3, 2, 2],
    ]);
    expect(new Set(weeks.flatMap((item) => item.lessons).map((item) => item.id)).size).toBe(6);
    expect(result.modules.find((item) => item.workspaceKind === 'experiment')?.title).toBe(
      '课程实验',
    );
    expect(result.onboarding?.completedAt).toBeTruthy();
  });
  it('is idempotent and retains material, outline and lesson file references', () => {
    const first = buildOnboardingSchedule(empty, input);
    first.modules[0].lessons[0].materialIds = ['material-1'];
    const again = buildOnboardingSchedule(first, input);
    expect(again.modules.map((item) => item.id)).toEqual(first.modules.map((item) => item.id));
    expect(again.modules[0].lessons[0]).toEqual(first.modules[0].lessons[0]);
    expect(again.onboarding?.outlineArtifactId).toBe('outline');
  });
  it('does not create a lab folder when the teacher selects no lab', () => {
    expect(buildOnboardingSchedule(empty, { ...input, hasLab: false }).modules).toHaveLength(3);
  });
  it('rejects invalid schedules and does not mutate the course', () => {
    expect(() => buildOnboardingSchedule(empty, { ...input, totalWeeks: 0 })).toThrow('有效');
    expect(() => buildOnboardingSchedule(empty, { ...input, lessonsPerWeek: 1.5 })).toThrow('有效');
    expect(empty.modules).toHaveLength(0);
  });
  it('does not silently delete existing weeks on resubmission', () => {
    const first = buildOnboardingSchedule(empty, input);
    expect(() => buildOnboardingSchedule(first, { ...input, totalWeeks: 1 })).toThrow(
      '不会自动删除',
    );
  });
});
