import { NextRequest, NextResponse } from 'next/server';
import { getTeacherCourseMembers } from '@/generated/teacher_platform_api';
import { isPlatformAuthEnabled, resolveTeacherId } from './platform-course-bridge';

type PlatformMember = {
  studentId: string;
  name: string;
  email?: string | null;
  enrolledAt?: string | null;
};

/** Read the authoritative platform enrollment roster. Never persist a copy. */
export async function platformCourseMembers(
  request: NextRequest,
  courseId: string,
): Promise<PlatformMember[] | undefined> {
  if (!isPlatformAuthEnabled()) return undefined;
  const teacherId = resolveTeacherId(request, undefined);
  if (!teacherId) throw new Error('请先登录平台');
  if (process.env.TEACHER_PLATFORM_CLIENT_MODE === 'generated') {
    const result = await getTeacherCourseMembers({
      baseUrl: `${(process.env.PLATFORM_AUTH_URL || '').replace(/\/$/, '')}/api/v1`,
      path: { course_id: courseId },
      headers: {
        'X-Teacher-Service-Key': process.env.PLATFORM_SERVICE_KEY || '',
        'X-Platform-Subject': teacherId,
      },
      cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(5000),
    });
    if (!result.response?.ok) {
      const error = result.error as { detail?: string } | undefined;
      throw new Error(error?.detail || '读取学生名单失败');
    }
    if (!Array.isArray(result.data?.members)) throw new Error('平台学生名单响应无效');
    return result.data.members;
  }
  const response = await fetch(
    `${process.env.PLATFORM_AUTH_URL}/api/v1/internal/teacher/courses/${encodeURIComponent(courseId)}/members`,
    {
      headers: {
        'X-Teacher-Service-Key': process.env.PLATFORM_SERVICE_KEY || '',
        'X-Platform-Subject': teacherId,
      },
      cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(5000),
    },
  );
  const data = await response.json() as { detail?: string; members?: PlatformMember[] };
  if (!response.ok) throw new Error(data.detail || '读取学生名单失败');
  return data.members ?? [];
}

export async function platformCourseMembersResponse(request: NextRequest, courseId: string) {
  try {
    return NextResponse.json({ members: await platformCourseMembers(request, courseId) ?? [] });
  } catch (error) {
    const message = error instanceof Error ? error.message : '读取学生名单失败';
    return NextResponse.json({ error: message }, { status: message === '请先登录平台' ? 401 : 502 });
  }
}
