import {
  publishCourseResource,
  type PublicationRequest,
} from '@/lib/server/course-resource-publication';
import { type NextRequest, NextResponse } from 'next/server';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import { readCourseMaterialBytes, readServerCourse } from '@/lib/server/course-space-storage';

export async function GET(
  _req: NextRequest,
  context: { params: Promise<{ courseId: string; materialId: string }> },
) {
  const { courseId, materialId } = await context.params;
  const course = await readServerCourse(courseId);
  const material = course?.materials.find((item) => item.id === materialId);
  if (!course || !material) return apiError('INVALID_REQUEST', 404, '课程材料不存在');
  const bytes = await readCourseMaterialBytes(material);
  return new NextResponse(new Uint8Array(bytes), {
    headers: {
      'content-type': material.mimeType || 'application/octet-stream',
      'content-length': String(bytes.length),
      'content-disposition': `inline; filename*=UTF-8''${encodeURIComponent(material.name)}`,
      'cache-control': 'private, no-store',
    },
  });
}

export async function PATCH(
  req: NextRequest,
  context: { params: Promise<{ courseId: string; materialId: string }> },
) {
  const { courseId, materialId } = await context.params;
  const course = await readServerCourse(courseId);
  if (!course?.materials.some((item) => item.id === materialId)) {
    return apiError('INVALID_REQUEST', 404, '课程材料不存在');
  }
  const body = (await req.json()) as { active?: boolean; placement?: PublicationRequest };
  if (body.active !== true) return apiError('INVALID_REQUEST', 409, '材料发布后不可撤回');
  try {
    return apiSuccess({
      material: await publishCourseResource(courseId, 'material', materialId, body.placement!),
    });
  } catch (error) {
    return apiError('INVALID_REQUEST', 409, error instanceof Error ? error.message : '发布失败');
  }
}
