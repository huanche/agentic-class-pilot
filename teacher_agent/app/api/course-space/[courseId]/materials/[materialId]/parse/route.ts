import { after, type NextRequest } from 'next/server';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import { buildRequestOrigin } from '@/lib/server/classroom-storage';
import { parseStoredCourseMaterial } from '@/lib/server/course-material-parser';
import { readServerCourse } from '@/lib/server/course-space-storage';

export const maxDuration = 30;

export async function POST(
  req: NextRequest,
  context: { params: Promise<{ courseId: string; materialId: string }> },
) {
  const { courseId, materialId } = await context.params;
  const course = await readServerCourse(courseId);
  const material = course?.materials.find((item) => item.id === materialId);
  if (!course || !material) return apiError('INVALID_REQUEST', 404, '课程材料不存在');
  if (material.status === 'parsing') return apiSuccess({ material, status: 'parsing' }, 202);
  after(() => parseStoredCourseMaterial({ courseId, materialId, baseUrl: buildRequestOrigin(req) }));
  return apiSuccess({ material: { ...material, status: 'parsing' }, status: 'parsing' }, 202);
}
