import { type NextRequest } from 'next/server';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import { readServerCourse, storeCourseMaterial } from '@/lib/server/course-space-storage';

export const runtime = 'nodejs';
const MAX_BYTES = 80 * 1024 * 1024;

export async function POST(req: NextRequest, context: { params: Promise<{ courseId: string }> }) {
  const { courseId } = await context.params;
  const course = await readServerCourse(courseId);
  if (!course) return apiError('INVALID_REQUEST', 404, '课程不存在');
  const form = await req.formData();
  const file = form.get('file');
  if (!(file instanceof File)) return apiError('MISSING_REQUIRED_FIELD', 400, '缺少课程材料');
  if (file.size > MAX_BYTES) return apiError('INVALID_REQUEST', 413, '课程材料不能超过 80MB');
  const material = await storeCourseMaterial({
    courseId,
    teacherId: course.teacherId,
    fileName: file.name,
    mimeType: file.type || 'application/octet-stream',
    bytes: Buffer.from(await file.arrayBuffer()),
  });
  return apiSuccess({ material }, 201);
}
