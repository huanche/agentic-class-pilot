import { type NextRequest } from 'next/server';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import {
  isStaleActiveJob,
  readCourseJob,
  STALE_ACTIVE_JOB_FAILURE,
  updateCourseJob,
} from '@/lib/server/course-space-storage';

export const dynamic = 'force-dynamic';

function canReadJob(req: NextRequest, teacherId: string) {
  return (
    process.env.PLATFORM_AUTH_ENABLED !== 'true' ||
    req.headers.get('x-platform-user-id') === teacherId ||
    req.headers.get('x-platform-admin') === 'true'
  );
}

export async function GET(req: NextRequest, context: { params: Promise<{ jobId: string }> }) {
  const { jobId } = await context.params;
  const job = await readCourseJob(jobId);
  if (!job) return apiError('INVALID_REQUEST', 404, '生成任务不存在');
  if (!canReadJob(req, job.teacherId)) return apiError('INVALID_REQUEST', 403, '无权查看此任务');
  // The job detail page polls this endpoint while the job looks active. A job
  // that has been silent past the stale window is dead (its process died with
  // a restart or a wedged LLM call) — flip it here so the page unsticks
  // instead of spinning on "Generating scene N/M" forever.
  if (isStaleActiveJob(job)) {
    const failed = await updateCourseJob(jobId, STALE_ACTIVE_JOB_FAILURE);
    return apiSuccess({ job: failed, done: true });
  }
  return apiSuccess({
    job,
    done: ['review', 'approved', 'failed', 'cancelled'].includes(job.status),
  });
}

export async function PATCH(req: NextRequest, context: { params: Promise<{ jobId: string }> }) {
  const { jobId } = await context.params;
  const job = await readCourseJob(jobId);
  if (!job) return apiError('INVALID_REQUEST', 404, '生成任务不存在');
  if (!canReadJob(req, job.teacherId)) return apiError('INVALID_REQUEST', 403, '无权取消此任务');
  const body = await req.json();
  if (body.action !== 'cancel' || !job.backgroundGeneration)
    return apiError('INVALID_REQUEST', 400, '此任务不支持该操作');
  const { cancelBackgroundCoursewareJob } = await import('@/lib/server/background-courseware');
  return apiSuccess({ job: await cancelBackgroundCoursewareJob(jobId), done: true });
}
