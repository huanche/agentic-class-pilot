import { NextRequest, NextResponse } from 'next/server';
import { isPlatformAuthEnabled, resolveTeacherId } from '@/lib/server/platform-course-bridge';

export async function GET(request: NextRequest, { params }: { params: Promise<{ courseId: string }> }) {
  if (!isPlatformAuthEnabled()) {
    return NextResponse.json({ error: '接入平台后可查看学生学情' }, { status: 503 });
  }
  const teacherId = resolveTeacherId(request, undefined);
  if (!teacherId) return NextResponse.json({ error: '请先登录平台' }, { status: 401 });
  const { courseId } = await params;
  const url = new URL(
    `${(process.env.PLATFORM_AUTH_URL || '').replace(/\/$/, '')}/api/v1/internal/teacher/courses/${encodeURIComponent(courseId)}/roster-progress`,
  );
  const student = request.nextUrl.searchParams.get('student');
  if (student) url.searchParams.set('student_id', student);
  try {
    const response = await fetch(url, {
      headers: {
        'X-Teacher-Service-Key': process.env.PLATFORM_SERVICE_KEY || '',
        'X-Platform-Subject': teacherId,
      },
      cache: 'no-store',
      redirect: 'error',
      signal: AbortSignal.timeout(10000),
    });
    if (!response.ok) {
      return NextResponse.json({ error: response.status === 404 ? '课程或学生不存在' : '学生学情读取失败' },
        { status: response.status });
    }
    return NextResponse.json(await response.json(), { headers: { 'Cache-Control': 'no-store' } });
  } catch (error) {
    console.error('读取班级学情失败', error);
    return NextResponse.json({ error: '学生学情服务暂不可用' }, { status: 503 });
  }
}
