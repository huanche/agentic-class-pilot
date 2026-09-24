import { type NextRequest } from 'next/server';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import { readKnowledgePackage, readServerCourse } from '@/lib/server/course-space-storage';

export const dynamic = 'force-dynamic';

export async function GET(_req: NextRequest, context: { params: Promise<{ courseId: string }> }) {
  const { courseId } = await context.params;
  const course = await readServerCourse(courseId);
  if (!course?.activeKnowledgePackageId) {
    return apiError('INVALID_REQUEST', 404, '该课程尚未发布知识包');
  }
  const knowledgePackage = await readKnowledgePackage(course.activeKnowledgePackageId);
  if (!knowledgePackage || knowledgePackage.status !== 'published') {
    return apiError('INVALID_REQUEST', 404, '当前知识包不可用');
  }
  return apiSuccess({ knowledgePackage });
}
