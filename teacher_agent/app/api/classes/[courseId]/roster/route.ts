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
      const body = await response.text();
      let detail: unknown;
      try {
        detail = JSON.parse(body).detail;
      } catch {
        // 网关的空白或 HTML 错误响应不代表课程、学生被删除。
        detail = undefined;
      }
      const missingCourse = response.status === 404 &&
        ['Course not found', '课程不存在', '课程映射不存在'].includes(String(detail));
      const missingStudent = response.status === 404 && detail === '该学生未加入本课程';
      const status = missingCourse || missingStudent ? 404 :
        [401, 403].includes(response.status) ? response.status : 503;
      const code = missingCourse ? 'COURSE_NOT_FOUND' : missingStudent ? 'STUDENT_NOT_ENROLLED' :
        status === 401 ? 'AUTH_REQUIRED' : status === 403 ? 'ACCESS_DENIED' : 'LEARNING_SERVICE_UNAVAILABLE';
      const error = missingCourse ? '课程不存在，请返回课程列表确认' :
        missingStudent ? '该学生未加入本课程' : status === 401 ? '登录已失效，请重新登录' :
        status === 403 ? '无权读取该课程的学生学情' : '学生学情服务暂不可用，请稍后重试或联系管理员';
      console.error('读取班级学情失败', {
        courseId, upstreamStatus: response.status, code,
        requestId: response.headers.get('x-request-id'),
      });
      return NextResponse.json({ error, code }, { status, headers: { 'Cache-Control': 'no-store' } });
    }
    return NextResponse.json(await response.json(), { headers: { 'Cache-Control': 'no-store' } });
  } catch (error) {
    console.error('读取班级学情失败', error);
    return NextResponse.json({ error: '学生学情服务暂不可用' }, { status: 503 });
  }
}
