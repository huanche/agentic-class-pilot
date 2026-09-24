import { NextRequest, NextResponse } from 'next/server';
import { isPlatformAuthEnabled, resolveTeacherId } from './platform-course-bridge';

export async function platformEnrollmentCode(request: NextRequest, courseId: string) {
  if (!isPlatformAuthEnabled()) return NextResponse.json({ standalone: true });
  const userId = resolveTeacherId(request, undefined);
  if (!userId) return NextResponse.json({ error: '请先登录平台' }, { status: 401 });
  try {
    const response = await fetch(`${process.env.PLATFORM_AUTH_URL}/api/v1/internal/teacher/courses/${encodeURIComponent(courseId)}/enrollment`, {
      headers: { 'X-Teacher-Service-Key': process.env.PLATFORM_SERVICE_KEY || '', 'X-Platform-Subject': userId },
      cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(5000),
    });
    const data = await response.json();
    return NextResponse.json(response.ok ? data : { error: data.detail || '读取选课码失败' }, { status: response.status });
  } catch {
    return NextResponse.json({ error: '平台暂不可用，请稍后重试' }, { status: 503 });
  }
}
