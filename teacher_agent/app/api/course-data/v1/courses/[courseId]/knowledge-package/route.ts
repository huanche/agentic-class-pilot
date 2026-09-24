import { type NextRequest } from 'next/server';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import { readKnowledgePackage, readServerCourse } from '@/lib/server/course-space-storage';
import { isCourseDatabaseConfigured, readPublishedKnowledgePackageFromDatabase } from '@/lib/server/course-space-database';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(_request: NextRequest, context: { params: Promise<{ courseId: string }> }) {
  const { courseId } = await context.params;
  const databasePackage = await readPublishedKnowledgePackageFromDatabase(courseId);
  let knowledgePackage = databasePackage;
  if (!knowledgePackage) {
    const course = await readServerCourse(courseId);
    knowledgePackage = course?.activeKnowledgePackageId
      ? await readKnowledgePackage(course.activeKnowledgePackageId) ?? undefined
      : undefined;
  }
  if (!knowledgePackage || knowledgePackage.status !== 'published') {
    return apiError('INVALID_REQUEST', 404, '该课程尚未发布可供学生智能体读取的知识包');
  }
  return apiSuccess({
    apiVersion: 'v1',
    source: isCourseDatabaseConfigured() && databasePackage ? 'database' : 'local-fallback',
    courseId,
    knowledgePackage,
  });
}
