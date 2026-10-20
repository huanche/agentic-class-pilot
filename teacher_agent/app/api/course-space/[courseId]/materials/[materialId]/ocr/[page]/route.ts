import { type NextRequest, NextResponse } from 'next/server';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import { readServerCourse } from '@/lib/server/course-space-storage';
import { resolveTeacherId, isValidCourseId } from '@/lib/server/platform-course-bridge';
import { readPptPagePreview, recognizePptPage } from '@/lib/server/pptx-image-ocr';

export const runtime = 'nodejs';
export const maxDuration = 90;
type Context = { params: Promise<{ courseId: string; materialId: string; page: string }> };

async function source(req: NextRequest, context: Context) {
  const { courseId, materialId, page: raw } = await context.params;
  const teacherId = resolveTeacherId(req, undefined);
  if (!teacherId) return apiError('INVALID_CREDENTIALS', 401, '请先登录');
  if (
    !isValidCourseId(courseId) ||
    !isValidCourseId(materialId) ||
    !/^\d{1,4}$/.test(raw) ||
    Number(raw) < 1
  ) {
    return apiError('INVALID_REQUEST', 400, '无效的材料或页码');
  }
  const course = await readServerCourse(courseId);
  if (!course || course.teacherId !== teacherId)
    return apiError('INVALID_REQUEST', 404, '课程材料不存在');
  const material = course.materials.find((item) => item.id === materialId);
  const page = Number(raw);
  if (!material || !/\.pptx$/i.test(material.name))
    return apiError('INVALID_REQUEST', 404, 'PPTX 材料不存在');
  if (page > (material.pageCount || 1000)) return apiError('INVALID_REQUEST', 400, '页码超出范围');
  return { material, page };
}

export async function GET(req: NextRequest, context: Context) {
  const input = await source(req, context);
  if (input instanceof NextResponse) return input;
  try {
    const image = await readPptPagePreview(input.material, input.page);
    return new NextResponse(new Uint8Array(image), {
      headers: {
        'content-type': 'image/jpeg',
        'cache-control': 'private, no-store',
      },
    });
  } catch {
    return apiError('PARSE_FAILED', 422, '无法读取本页图片，请重新上传原始 PPTX');
  }
}

export async function POST(req: NextRequest, context: Context) {
  const input = await source(req, context);
  if (input instanceof NextResponse) return input;
  try {
    return apiSuccess({ result: await recognizePptPage(input.material, input.page, req.signal) });
  } catch (error) {
    if (req.signal.aborted) return apiError('PARSE_FAILED', 499, '已取消识别');
    const message = error instanceof Error ? error.message : '';
    return apiError(
      'PARSE_FAILED',
      422,
      /^(尚未配置|图片文字识别服务|本页识别|未识别到)/.test(message)
        ? message
        : '本页图片识别失败，请重试',
    );
  }
}
