import type { CourseArtifactJob } from './types';
import type { CourseGenerationTask } from '@/lib/store/course-generation-task';

export type CoursewareTaskProgress = {
  id: string;
  status: 'queued' | 'running' | 'review' | 'completed' | 'failed' | 'cancelled';
  progress: number;
  message: string;
  job?: CourseArtifactJob;
  task?: CourseGenerationTask;
};

export const isCoursewareTaskRunning = (status: CoursewareTaskProgress['status']) =>
  status === 'queued' || status === 'running' || status === 'review';

/** Settle the shared submission lock as well as the button's display state. */
export function reconcileCoursewareTaskSnapshot(
  task: CourseGenerationTask | null,
  jobs: CourseArtifactJob[],
): CourseGenerationTask | null {
  if (!task?.serverJobId) return task;
  const job = jobs.find((item) => item.id === task.serverJobId && item.courseId === task.courseId);
  if (!job) return task;
  const status =
    job.status === 'review' || job.status === 'approved'
      ? 'completed'
      : job.status === 'queued'
        ? 'running'
        : job.status;
  const step = job.backgroundGeneration?.completedPages ?? task.step;
  const total = job.backgroundGeneration?.totalPages ?? task.total;
  if (
    task.status === status &&
    task.message === job.message &&
    task.step === step &&
    task.total === total
  )
    return task;
  return { ...task, status, message: job.message, step, total };
}

function percentage(value: number, completed = false) {
  return completed
    ? 100
    : Math.min(99, Math.max(0, Math.round(Number.isFinite(value) ? value : 0)));
}

/** Persisted server state takes precedence over the browser's submission snapshot. */
export function resolveCoursewareTaskProgress({
  courseId,
  lessonId,
  jobs,
  task,
}: {
  courseId: string;
  lessonId?: string;
  jobs: CourseArtifactJob[];
  task: CourseGenerationTask | null;
}): CoursewareTaskProgress | null {
  const courseJobs = jobs
    .filter((job) => job.courseId === courseId && job.artifactType === 'lesson-courseware')
    .sort((a, b) => b.createdAt - a.createdAt);
  const fromJob = (job: CourseArtifactJob): CoursewareTaskProgress => {
    const completed = job.status === 'review' || job.status === 'approved';
    return {
      id: job.id,
      status: job.status === 'review' || job.status === 'approved' ? 'completed' : job.status,
      progress: percentage(job.progress, completed),
      message: job.message,
      job,
    };
  };
  const active = courseJobs.find((job) => job.status === 'queued' || job.status === 'running');
  if (active) return fromJob(active);
  if (task?.courseId === courseId) {
    const persisted = task.serverJobId
      ? courseJobs.find((job) => job.id === task.serverJobId)
      : undefined;
    if (persisted) {
      // A finished task should not mask a newer failed attempt or a different lesson.
      if (
        !lessonId ||
        (persisted.scope.type === 'lesson' && persisted.scope.lessonId === lessonId)
      ) {
        const latest = courseJobs.find(
          (job) => !lessonId || (job.scope.type === 'lesson' && job.scope.lessonId === lessonId),
        );
        return fromJob(latest ?? persisted);
      }
    } else if (isCoursewareTaskRunning(task.status) || task.status === 'failed') {
      return {
        id: task.id,
        status: task.status,
        progress: percentage(task.total > 0 ? (task.step / task.total) * 100 : 0),
        message: task.message,
        task,
      };
    }
  }
  const latest = courseJobs.find(
    (job) => !lessonId || (job.scope.type === 'lesson' && job.scope.lessonId === lessonId),
  );
  return latest ? fromJob(latest) : null;
}
