import { beforeEach, describe, expect, it, vi } from 'vitest';
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
  it.each(['completed', 'failed', 'cancelled'] as const)(
    'unlocks submission after %s',
    (status) => {
      useCourseGenerationTask.getState().setTask({ ...task, status });
      expect(isGenerationTaskActive(useCourseGenerationTask.getState().task)).toBe(false);
      expect(useCourseGenerationTask.getState().task?.status).toBe(status);
    },
  );
  it('aborts an outline runtime, releases its lock and ignores late progress', async () => {
    const current = { ...task, id: 'cancel-outline', status: 'review' as const };
    const controller = new AbortController();
    useCourseGenerationTask.getState().setTask(current);
    useCourseGenerationTask.getState().setRuntimeId(current.id);
    const unregister = useCourseGenerationTask
      .getState()
      .registerCancelHandler(current.id, () => controller.abort());
    await useCourseGenerationTask.getState().cancelTask(current.id);
    expect(controller.signal.aborted).toBe(true);
    expect(useCourseGenerationTask.getState().runtimeId).toBeNull();
    expect(isGenerationTaskActive(useCourseGenerationTask.getState().task)).toBe(false);
    const next = { ...task, id: 'new-attempt' };
    useCourseGenerationTask.getState().setTask(next);
    useCourseGenerationTask.getState().setTask({ ...current, status: 'running' });
    expect(useCourseGenerationTask.getState().task).toEqual(next);
    unregister();
  });
  it('waits for cancellation of a submitting worker and deduplicates repeated clicks', async () => {
    const current = { ...task, id: 'cancel-handoff' };
    useCourseGenerationTask.getState().setTask(current);
    let finish!: () => void;
    const stop = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        }),
    );
    const unregister = useCourseGenerationTask.getState().registerCancelHandler(current.id, stop);
    const first = useCourseGenerationTask.getState().cancelTask(current.id);
    const second = useCourseGenerationTask.getState().cancelTask(current.id);
    expect(second).toBe(first);
    await Promise.resolve();
    expect(isGenerationTaskActive(useCourseGenerationTask.getState().task)).toBe(true);
    finish();
    await first;
    expect(stop).toHaveBeenCalledOnce();
    expect(useCourseGenerationTask.getState().task?.status).toBe('cancelled');
    unregister();
  });
  it('keeps a cancellation failure visible and allows retry', async () => {
    const current = { ...task, id: 'cancel-retry' };
    useCourseGenerationTask.getState().setTask(current);
    const stop = vi.fn().mockRejectedValueOnce(new Error('network')).mockResolvedValue(undefined);
    const unregister = useCourseGenerationTask.getState().registerCancelHandler(current.id, stop);
    await expect(useCourseGenerationTask.getState().cancelTask(current.id)).rejects.toThrow(
      'network',
    );
    expect(isGenerationTaskActive(useCourseGenerationTask.getState().task)).toBe(true);
    await useCourseGenerationTask.getState().cancelTask(current.id);
    expect(useCourseGenerationTask.getState().task?.status).toBe('cancelled');
    unregister();
  });
  it('does not cancel a different task or settle a server job without confirmation', async () => {
    useCourseGenerationTask
      .getState()
      .setTask({ ...task, id: 'server-owned', serverJobId: 'cw_server' });
    await useCourseGenerationTask.getState().cancelTask('different');
    await useCourseGenerationTask.getState().cancelTask('server-owned');
    expect(isGenerationTaskActive(useCourseGenerationTask.getState().task)).toBe(true);
  });
});
