import { type NextRequest } from 'next/server';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import { createServerCourse, listServerCourses, readServerCourse } from '@/lib/server/course-space-storage';
import {
  isDelegatedByPlatform,
  isValidCourseId,
  platformProvidedCourseId,
  registerCourseWithPlatform,
  resolveTeacherId,
} from '@/lib/server/platform-course-bridge';
import { type CreateCourseSpaceInput } from '@/lib/course-space/types';

export const dynamic = 'force-dynamic';

export async function GET(req: NextRequest) {
  const teacherId = resolveTeacherId(req, req.nextUrl.searchParams.get('teacherId') || undefined);
  if (!teacherId) return apiError('INVALID_CREDENTIALS', 401, '请先登录平台');
  try {
    return apiSuccess({ courses: await listServerCourses(teacherId) });
  } catch (error) {
    console.error('course storage unavailable:', error);
    return apiError('SERVICE_UNAVAILABLE', 503, '课程存储暂不可用（数据库不可达或配置错误），请稍后重试');
  }
}

export async function POST(req: NextRequest) {
  const body = (await req.json()) as Partial<CreateCourseSpaceInput>;
  const teacherId = resolveTeacherId(req, body.teacherId);
  if (!teacherId) return apiError('INVALID_CREDENTIALS', 401, '请先登录平台');
  const id = platformProvidedCourseId(body);
  if (id && !isValidCourseId(id)) return apiError('INVALID_REQUEST', 400, 'Invalid course ID');
  if (id) {
    // Idempotent: platform-provisioned or retried registration for a known id.
    const existing = await readServerCourse(id);
    if (existing) {
      if (existing.teacherId !== teacherId) return apiError('INVALID_CREDENTIALS', 403, '无权访问课程');
      if (!isDelegatedByPlatform(req)) {
        try {
          await registerCourseWithPlatform(existing);
        } catch {
          return apiError('SERVICE_UNAVAILABLE', 502, '课程存在，但平台课程管理登记失败，请稍后重试');
        }
      }
      return apiSuccess({ course: existing });
    }
  }
  if (!body.title?.trim()) return apiError('MISSING_REQUIRED_FIELD', 400, '课程名称不能为空');
  let course;
  try {
    course = await createServerCourse({
      id,
      teacherId,
      title: body.title,
      subject: body.subject,
      gradeBand: body.gradeBand,
      term: body.term,
      description: body.description,
    });
  } catch (error) {
    console.error('course storage unavailable:', error);
    return apiError('SERVICE_UNAVAILABLE', 503, '课程存储暂不可用（数据库不可达或配置错误），请稍后重试');
  }
  if (!isDelegatedByPlatform(req)) {
    try {
      await registerCourseWithPlatform(course);
    } catch {
      return apiError('SERVICE_UNAVAILABLE', 502, '课程已创建，但平台课程管理登记失败，请稍后重试');
    }
  }
  return apiSuccess({ course }, 201);
}
