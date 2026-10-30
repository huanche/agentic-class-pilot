import { type NextRequest, NextResponse } from 'next/server';
import { readCourseJob } from '@/lib/server/course-space-storage';
import { readCourseKnowledgeExtractionJob } from '@/lib/server/course-knowledge-store';

export const dynamic = 'force-dynamic';

/**
 * Resolve a background job to its owning course so the platform can enforce
 * course-scoped access without reading teacher job tables. kind selects the
 * job family: artifact (course-space/jobs) or graph (knowledge-graph/jobs).
 */
export async function GET(
  request: NextRequest,
  context: { params: Promise<{ jobId: string }> },
) {
  if (process.env.PLATFORM_AUTH_ENABLED !== 'true' ||
      request.headers.get('x-platform-delegated') !== 'true') {
    return NextResponse.json({ error: 'Platform service authorization required' }, { status: 403 });
  }
  const kind = request.nextUrl.searchParams.get('kind') === 'graph' ? 'graph' : 'artifact';
  const { jobId } = await context.params;
  const job = kind === 'graph'
    ? await readCourseKnowledgeExtractionJob(jobId)
    : await readCourseJob(jobId);
  if (!job) return NextResponse.json({ error: 'Task not found' }, { status: 404 });
  return NextResponse.json({ courseId: job.courseId });
}
