import { type NextRequest } from 'next/server';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import { readCourseJob } from '@/lib/server/course-space-storage';

export const dynamic = 'force-dynamic';

export async function GET(_req: NextRequest, context: { params: Promise<{ jobId: string }> }) {
  const { jobId } = await context.params;
  const job = await readCourseJob(jobId);
  if (!job) return apiError('INVALID_REQUEST', 404, '生成任务不存在');
  return apiSuccess({ job, done: ['review', 'approved', 'failed'].includes(job.status) });
}
