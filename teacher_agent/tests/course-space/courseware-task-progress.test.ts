import { describe, expect, it } from 'vitest';
import type { CourseArtifactJob } from '@/lib/course-space/types';
import type { CourseGenerationTask } from '@/lib/store/course-generation-task';
import {
  resolveCoursewareTaskProgress,
  reconcileCoursewareTaskSnapshot,
} from '@/lib/course-space/courseware-task-progress';
import { isGenerationTaskActive } from '@/lib/store/course-generation-task';

const job: CourseArtifactJob = {
  id: 'server-job',
  courseId: 'python',
  teacherId: 'teacher',
  artifactType: 'lesson-courseware',
  scope: { type: 'lesson', lessonId: 'lesson-1' },
  status: 'running',
  progress: 37,
  message: '生成第4页配音',
  backgroundGeneration: {
    classroomId: 'classroom',
    completedPages: 3,
    totalPages: 12,
    phase: 'audio',
  },
  createdAt: 100,
  updatedAt: 200,
};
const task: CourseGenerationTask = {
  id: job.id,
  serverJobId: job.id,
  courseId: job.courseId,
  title: 'Python',
  status: 'running',
  message: '刚提交后台',
  step: 0,
  total: 12,
};
const resolve = (
  jobs: CourseArtifactJob[],
  clientTask: CourseGenerationTask | null = null,
  lessonId = 'lesson-1',
) => resolveCoursewareTaskProgress({ courseId: 'python', lessonId, jobs, task: clientTask });

describe('courseware button progress from real job state', () => {
  it.each(['review', 'approved', 'cancelled', 'failed'] as const)(
    'unlocks generation after the background job is %s',
    (status) => {
      const updated = reconcileCoursewareTaskSnapshot(task, [{ ...job, status }]);
      expect(isGenerationTaskActive(updated)).toBe(false);
      expect(updated?.step).toBe(3);
    },
  );
  it('does not settle another course or a foreground outline review', () => {
    expect(
      reconcileCoursewareTaskSnapshot(task, [{ ...job, courseId: 'chemistry', status: 'review' }]),
    ).toBe(task);
    const foreground = { ...task, serverJobId: undefined, status: 'review' as const };
    expect(reconcileCoursewareTaskSnapshot(foreground, [job])).toBe(foreground);
  });
  it('restores saved progress after reopening without browser state', () => {
    expect(resolve([job])).toMatchObject({
      status: 'running',
      progress: 37,
      job: { backgroundGeneration: { completedPages: 3 } },
    });
  });
  it('shows a running job while viewing another lesson', () => {
    expect(resolve([job], null, 'lesson-2')?.id).toBe(job.id);
  });
  it('uses live progress instead of the submission snapshot', () => {
    expect(resolve([job], task)?.progress).toBe(37);
  });
  it.each(['cancelled', 'failed', 'review', 'approved'] as const)(
    'does not revive a %s server job from the running browser snapshot',
    (status) => {
      expect(resolve([{ ...job, status }], task)?.status).toBe(
        status === 'review' || status === 'approved' ? 'completed' : status,
      );
    },
  );
  it('shows a later failed attempt instead of the previous completed browser task', () => {
    const newer = { ...job, id: 'retry-job', status: 'failed' as const, createdAt: 300 };
    expect(resolve([{ ...job, status: 'review' }, newer], task)).toMatchObject({
      id: 'retry-job',
      status: 'failed',
    });
  });
  it('keeps an old failed lesson from blocking generation in another lesson', () => {
    expect(resolve([{ ...job, status: 'failed' }], task, 'lesson-2')).toBeNull();
  });
  it('does not confuse another course or outline job with courseware generation', () => {
    expect(
      resolve(
        [
          { ...job, courseId: 'chemistry' },
          { ...job, artifactType: 'course-outline' },
        ],
        { ...task, courseId: 'chemistry' },
      ),
    ).toBeNull();
  });
  it('keeps foreground outline review accessible before the background handoff', () => {
    expect(
      resolve([], {
        ...task,
        serverJobId: undefined,
        status: 'review',
        step: 1,
        total: 4,
        url: '/generation-preview',
      }),
    ).toMatchObject({ status: 'review', progress: 25 });
  });
  it('surfaces foreground failures as well as server failures', () => {
    expect(
      resolve([], { ...task, serverJobId: undefined, status: 'failed', message: '大纲生成失败' }),
    ).toMatchObject({ status: 'failed', message: '大纲生成失败' });
  });
  it('reserves 100 percent for completed generation', () => {
    expect(resolve([{ ...job, progress: 100 }])?.progress).toBe(99);
    expect(resolve([{ ...job, status: 'review', progress: 98 }])?.progress).toBe(100);
  });
  it.each([NaN, -20, Infinity])('sanitizes invalid progress %s', (progress) => {
    expect(resolve([{ ...job, progress }])?.progress).toBe(0);
  });
});
