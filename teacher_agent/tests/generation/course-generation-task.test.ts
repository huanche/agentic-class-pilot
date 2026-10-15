import { beforeEach, describe, expect, it } from 'vitest';
import {
  isGenerationTaskActive,
  useCourseGenerationTask,
  type CourseGenerationTask,
} from '@/lib/store/course-generation-task';
const task: CourseGenerationTask = {
  id: 'generation-1',
  courseId: 'course-1',
  title: '第1周课件',
  status: 'running',
  message: '生成场景',
  step: 2,
  total: 5,
};
describe('course generation task lifecycle', () => {
  beforeEach(() => useCourseGenerationTask.setState({ task: null }));
  it('retains task progress independently of the chat session', () => {
    useCourseGenerationTask.getState().setTask(task);
    expect(isGenerationTaskActive(useCourseGenerationTask.getState().task)).toBe(true);
    useCourseGenerationTask.getState().setTask({ ...task, step: 3, message: '生成讲稿' });
    expect(useCourseGenerationTask.getState().task).toMatchObject({
      id: task.id,
      courseId: task.courseId,
      step: 3,
    });
  });
  it('keeps new task submission locked during teacher review', () => {
    expect(isGenerationTaskActive({ ...task, status: 'review' })).toBe(true);
  });
  it.each(['completed', 'failed'] as const)('unlocks submission after %s', (status) => {
    useCourseGenerationTask.getState().setTask({ ...task, status });
    expect(isGenerationTaskActive(useCourseGenerationTask.getState().task)).toBe(false);
    expect(useCourseGenerationTask.getState().task?.status).toBe(status);
  });
});
