import { NextRequest, NextResponse } from 'next/server';
import { getTeacherCourseEnrollment } from '@/generated/teacher_platform_api';
import { isPlatformAuthEnabled, resolveTeacherId } from './platform-course-bridge';

export async function platformEnrollmentCode(request: NextRequest, courseId: string) {
  if (!isPlatformAuthEnabled()) return NextResponse.json({ standalone: true });
  const userId = resolveTeacherId(request, undefined);
  if (!userId) return NextResponse.json({ error: '请先登录平台' }, { status: 401 });
  try {
    const result = await getTeacherCourseEnrollment({
      baseUrl: `${(process.env.PLATFORM_AUTH_URL || '').replace(/\/$/, '')}/api/v1`,
      path: { course_id: courseId },
      headers: { 'X-Teacher-Service-Key': process.env.PLATFORM_SERVICE_KEY || '', 'X-Platform-Subject': userId },
      cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(5000),
    });
    const status = result.response?.status ?? 503;
    if (result.response?.ok && result.data) return NextResponse.json(result.data);
    const error = result.error as { detail?: string } | undefined;
    return NextResponse.json({ error: error?.detail || '读取选课码失败' }, { status });
  } catch {
    return NextResponse.json({ error: '平台暂不可用，请稍后重试' }, { status: 503 });
  }
}
