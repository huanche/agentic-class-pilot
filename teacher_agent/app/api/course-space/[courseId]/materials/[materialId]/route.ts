import { type NextRequest, NextResponse } from 'next/server';
import { nanoid } from 'nanoid';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import {
  readCourseMaterialBytes,
  readServerCourse,
  updateServerCourse,
} from '@/lib/server/course-space-storage';

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
  const body = (await req.json()) as { active?: boolean };
  const active = body.active === true;
  const material = course.materials.find((item) => item.id === materialId)!;
  if (!active) {
    return apiError('INVALID_REQUEST', 409, '材料发布到班级后不可撤回');
  }
  if (material.classPublicationId) {
    return apiSuccess({ material });
  }
  if (course.status !== 'active') {
    return apiError('INVALID_REQUEST', 409, '请先发布课程，再将材料发布到班级');
  }
  const now = Date.now();
  const updated = await updateServerCourse(courseId, (current) => ({
    ...current,
    materials: current.materials.map((item) =>
      item.id === materialId
        ? {
            ...item,
            classVisible: active,
            activatedAt: now,
            classPublicationId: `CLS-M-${nanoid(12)}`,
            classPublishedAt: now,
            updatedAt: now,
          }
        : item,
    ),
  }));
  return apiSuccess({ material: updated.materials.find((item) => item.id === materialId) });
}
