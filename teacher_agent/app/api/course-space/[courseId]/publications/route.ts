import { type NextRequest } from 'next/server';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import { publishCourseResource } from '@/lib/server/course-resource-publication';
export async function POST(req: NextRequest, context: { params: Promise<{ courseId: string }> }) {
  const { courseId } = await context.params;
  const body = await req.json().catch(() => null);
  if (
    !body ||
    !['artifact', 'material', 'course-file'].includes(body.kind) ||
    typeof body.id !== 'string'
  )
    return apiError('INVALID_REQUEST', 400, '请选择待发布文件');
  try {
    return apiSuccess({
      resource: await publishCourseResource(courseId, body.kind, body.id, body.placement),
    });
  } catch (error) {
    return apiError('INVALID_REQUEST', 409, error instanceof Error ? error.message : '发布失败');
  }
}
