import { type NextRequest } from 'next/server';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import { readMaterialExtraction, readServerCourse } from '@/lib/server/course-space-storage';

export const dynamic = 'force-dynamic';

export async function GET(
  _req: NextRequest,
  context: { params: Promise<{ courseId: string; materialId: string }> },
) {
  const { courseId, materialId } = await context.params;
  const course = await readServerCourse(courseId);
  const material = course?.materials.find((item) => item.id === materialId);
  if (!course || !material) return apiError('INVALID_REQUEST', 404, '课程材料不存在');
  if (material.status !== 'ready') return apiError('INVALID_REQUEST', 409, '课程材料尚未解析完成');
  const extraction = await readMaterialExtraction(materialId);
  if (!extraction) return apiError('INVALID_REQUEST', 404, '课程材料解析结果不存在');
  return apiSuccess({ extraction });
}
