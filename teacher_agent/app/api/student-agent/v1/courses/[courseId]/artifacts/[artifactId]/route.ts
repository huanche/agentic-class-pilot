import { type NextRequest } from 'next/server';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import { authorizeStudentAgent } from '@/lib/server/student-agent-auth';
import { readCourseArtifact, readPublishedKnowledgePackage } from '@/lib/server/course-space-storage';

export async function GET(request: NextRequest, context: { params: Promise<{ courseId: string; artifactId: string }> }) {
  const denied = authorizeStudentAgent(request);
  if (denied) return denied;
  const { courseId, artifactId } = await context.params;
  const [artifact, knowledgePackage] = await Promise.all([
    readCourseArtifact(artifactId),
    readPublishedKnowledgePackage(courseId),
  ]);
  if (!artifact || artifact.courseId !== courseId || artifact.status !== 'published' || !knowledgePackage) {
    return apiError('INVALID_REQUEST', 404, '已发布教学产物不存在');
  }
  return apiSuccess({ schemaVersion: '1.0', artifact });
}
