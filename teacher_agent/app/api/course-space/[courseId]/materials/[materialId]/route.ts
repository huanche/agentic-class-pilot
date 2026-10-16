import {
  publishCourseResource,
  type PublicationRequest,
} from '@/lib/server/course-resource-publication';
import { type NextRequest, NextResponse } from 'next/server';
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
  const body = (await req.json()) as { active?: boolean; placement?: PublicationRequest };
  if (typeof body.active !== 'boolean')
    return apiError('INVALID_REQUEST', 400, '请选择发布或取消发布');
  if (!body.active) {
    const updated = await updateServerCourse(course.id, (current) => ({
      ...current,
      updatedAt: Date.now(),
      materials: current.materials.map((item) =>
        item.id === materialId
          ? {
              ...item,
              classVisible: false,
              classPublicationId: undefined,
              classPublishedAt: undefined,
              publicationPlacement: undefined,
              activatedAt: undefined,
              updatedAt: Date.now(),
            }
          : item,
      ),
    }));
    return apiSuccess({ material: updated.materials.find((item) => item.id === materialId) });
  }
  try {
    return apiSuccess({
      material: await publishCourseResource(courseId, 'material', materialId, body.placement!),
    });
  } catch (error) {
    return apiError('INVALID_REQUEST', 409, error instanceof Error ? error.message : '发布失败');
  }
}

export async function DELETE(
  _req: NextRequest,
  context: { params: Promise<{ courseId: string; materialId: string }> },
) {
  const { courseId, materialId } = await context.params;
  const course = await readServerCourse(courseId);
  const material = course?.materials.find((item) => item.id === materialId);
  if (!course || !material) return apiError('INVALID_REQUEST', 404, '课程材料不存在');
  if (material.status === 'parsing')
    return apiError('INVALID_REQUEST', 409, '材料正在解析，请完成后再删除');
  // Retain the original bytes for citations; remove the active course references.
  await updateServerCourse(course.id, (current) => ({
    ...current,
    updatedAt: Date.now(),
    materials: current.materials.filter((item) => item.id !== materialId),
    modules: current.modules.map((courseModule) => ({
      ...courseModule,
      lessons: courseModule.lessons.map((lesson) => ({
        ...lesson,
        materialIds: lesson.materialIds.filter((id) => id !== materialId),
      })),
    })),
  }));
  return apiSuccess({ deleted: materialId });
}
