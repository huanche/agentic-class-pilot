import { type NextRequest } from 'next/server';
import { apiSuccess } from '@/lib/server/api-response';
import { listCourseArtifacts } from '@/lib/server/course-space-storage';
import { isCourseDatabaseConfigured, listCourseArtifactsFromDatabase } from '@/lib/server/course-space-database';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/** Student-agent-safe feed: only teacher-approved or published artifacts are exposed. */
export async function GET(_request: NextRequest, context: { params: Promise<{ courseId: string }> }) {
  const { courseId } = await context.params;
  const statuses = ['approved', 'published'] as const;
  const databaseArtifacts = await listCourseArtifactsFromDatabase(courseId, [...statuses]);
  const artifacts = databaseArtifacts ?? (await listCourseArtifacts(courseId)).filter((item) => statuses.includes(item.status as typeof statuses[number]));
  return apiSuccess({
    apiVersion: 'v1',
    source: isCourseDatabaseConfigured() && databaseArtifacts ? 'database' : 'local-fallback',
    courseId,
    artifacts: artifacts.map((artifact) => ({
      id: artifact.id,
      type: artifact.type,
      title: artifact.title,
      content: artifact.content,
      htmlContent: artifact.htmlContent,
      status: artifact.status,
      scope: artifact.scope,
      citations: artifact.citations,
      approvedAt: artifact.approvedAt,
      updatedAt: artifact.updatedAt,
    })),
  });
}
