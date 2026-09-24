import { after, type NextRequest } from 'next/server';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import { readCourseKnowledgeExtractionJob, saveCourseKnowledgeExtractionJob } from '@/lib/server/course-knowledge-store';
import { runCourseKnowledgeExtractionJob } from '@/lib/server/course-knowledge-extraction';

export const dynamic = 'force-dynamic';

export async function GET(_request: NextRequest, context: { params: Promise<{ jobId: string }> }) {
  const { jobId } = await context.params;
  const job = await readCourseKnowledgeExtractionJob(jobId);
  return job ? apiSuccess({ job }) : apiError('INVALID_REQUEST', 404, '知识抽取任务不存在');
}

export async function POST(_request: NextRequest, context: { params: Promise<{ jobId: string }> }) {
  const { jobId } = await context.params;
  const job = await readCourseKnowledgeExtractionJob(jobId);
  if (!job) return apiError('INVALID_REQUEST', 404, '知识抽取任务不存在');
  if (job.status === 'review') return apiError('INVALID_REQUEST', 409, '任务已经完成');
  const leaseExpired = job.status === 'running' && Date.now() - job.updatedAt > 2 * 60_000;
  if (job.status === 'running' && !leaseExpired) return apiError('INVALID_REQUEST', 409, '任务仍在执行');
  const resumed = { ...job, status:'queued' as const, phase:'queued' as const, progress:0,
    message:'等待恢复知识抽取', error:undefined, updatedAt:Date.now() };
  await saveCourseKnowledgeExtractionJob(resumed);
  after(() => runCourseKnowledgeExtractionJob(jobId).then(() => undefined));
  return apiSuccess({ job:resumed }, 202);
}
