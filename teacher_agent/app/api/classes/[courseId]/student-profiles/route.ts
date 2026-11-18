import { NextRequest, NextResponse } from 'next/server';
import { isPlatformAuthEnabled, resolveTeacherId } from '@/lib/server/platform-course-bridge';
import { parseRosterPdf } from '@/lib/server/student-roster-pdf';

type Context = { params: Promise<{ courseId: string }> };

async function directory(request: NextRequest, context: Context, method = 'GET', body?: string) {
  if (!isPlatformAuthEnabled()) return NextResponse.json({ error: '接入平台后可管理学生名单' }, { status: 503 });
  const teacher = resolveTeacherId(request, undefined);
  if (!teacher) return NextResponse.json({ error: '请先登录平台' }, { status: 401 });
  const { courseId } = await context.params;
  try {
    const response = await fetch(`${(process.env.PLATFORM_AUTH_URL || '').replace(/\/$/, '')}/api/v1/internal/teacher/courses/${encodeURIComponent(courseId)}/student-profiles`, {
      method, body, cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(15000),
      headers: { 'X-Teacher-Service-Key': process.env.PLATFORM_SERVICE_KEY || '',
        'X-Platform-Subject': teacher, ...(body ? { 'Content-Type': 'application/json' } : {}) },
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => null);
      const status = [401, 403, 409, 422].includes(response.status) ? response.status : 503;
      console.error('课程名单请求失败', { courseId, method, status: response.status });
      return NextResponse.json({ error: status === 503 ? '学生名单服务暂不可用，请联系管理员检查服务与数据库版本' :
        typeof detail?.detail === 'string' ? detail.detail : '名单请求失败，请核对输入与权限' }, { status });
    }
    return NextResponse.json(await response.json(), { headers: { 'Cache-Control': 'no-store' } });
  } catch (error) {
    console.error('课程名单服务连接失败', error);
    return NextResponse.json({ error: '学生名单服务暂不可用，请稍后重试' }, { status: 503 });
  }
}

export async function GET(request: NextRequest, context: Context) {
  return directory(request, context);
}

export async function PUT(request: NextRequest, context: Context) {
  const body = await request.text();
  if (new TextEncoder().encode(body).length > 2 * 1024 * 1024) {
    return NextResponse.json({ error: '名单内容过大' }, { status: 413 });
  }
  return directory(request, context, 'PUT', body);
}

export async function POST(request: NextRequest, context: Context) {
  // 解析前验证课程归属，避免无权教师读取其他课程的账号名单。
  const result = await directory(request, context);
  if (!result.ok) return result;
  if (Number(request.headers.get('content-length')) > 11 * 1024 * 1024) {
    return NextResponse.json({ error: 'PDF 不能超过 10 MB' }, { status: 413 });
  }
  try {
    const form = await request.formData();
    const file = form.get('file');
    if (!(file instanceof File) || !file.name.toLowerCase().endsWith('.pdf')) {
      return NextResponse.json({ error: '请选择 PDF 格式的学生名单' }, { status: 422 });
    }
    if (file.size > 10 * 1024 * 1024) return NextResponse.json({ error: 'PDF 不能超过 10 MB' }, { status: 413 });
    const parsed = await parseRosterPdf(new Uint8Array(await file.arrayBuffer()));
    return NextResponse.json({ ...await result.json(), imported: parsed.entries, warnings: parsed.warnings },
      { headers: { 'Cache-Control': 'no-store' } });
  } catch (error) {
    console.error('名单 PDF 解析失败', error instanceof Error ? error.name : 'UnknownError');
    return NextResponse.json({ error: error instanceof Error ? error.message : 'PDF 解析失败，请检查文件' }, { status: 422 });
  }
}
