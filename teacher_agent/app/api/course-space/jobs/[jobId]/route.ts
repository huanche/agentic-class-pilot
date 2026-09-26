import { type NextRequest } from 'next/server';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import {
  isStaleActiveJob,
  readCourseJob,
  STALE_ACTIVE_JOB_FAILURE,
  updateCourseJob,
} from '@/lib/server/course-space-storage';

export const dynamic = 'force-dynamic';

export async function GET(_req: NextRequest, context: { params: Promise<{ jobId: string }> }) {
  const { jobId } = await context.params;
  const job = await readCourseJob(jobId);
  if (!job) return apiError('INVALID_REQUEST', 404, '生成任务不存在');
  // The job detail page polls this endpoint while the job looks active. A job
  // that has been silent past the stale window is dead (its process died with
  // a restart or a wedged LLM call) — flip it here so the page unsticks
  // instead of spinning on "Generating scene N/M" forever.
  if (isStaleActiveJob(job)) {
    const failed = await updateCourseJob(jobId, STALE_ACTIVE_JOB_FAILURE);
    return apiSuccess({ job: failed, done: true });
  }
  return apiSuccess({ job, done: ['review', 'approved', 'failed'].includes(job.status) });
}
