import { NextRequest, NextResponse } from 'next/server';

import { createLogger } from '@/lib/logger';
import { authorizeTeacherRequest } from '@/generated/teacher_platform_api';

const log = createLogger('Platform auth');

/**
 * Delegate browser and service identity to the platform; fail closed.
 *
 * Ported from the legacy teacher service integration (platform-auth.ts, verified
 * against the platform teacher bridge on :3100). Every request is authorized by
 * `POST {PLATFORM_AUTH_URL}/api/v1/internal/teacher/authorize`; caller-supplied
 * `x-platform-user-id` headers are stripped so the identity below is trusted.
 */
export async function platformMiddleware(request: NextRequest): Promise<NextResponse> {
  // Public static assets (agent avatars) carry no data; embedding pages under
  // the gateway need them without a platform round-trip.
  if (request.nextUrl.pathname === '/api/health') return NextResponse.next();
  if (request.nextUrl.pathname.startsWith('/avatars/')) return NextResponse.next();
  if (['/brand-mark.png', '/mentra-icon.svg', '/mentra-logo.svg', '/logo-horizontal.png'].includes(request.nextUrl.pathname)) {
    return NextResponse.next();
  }
  const headers = new Headers(request.headers);
  headers.delete('x-platform-user-id');
  headers.delete('x-platform-admin');
  headers.delete('x-platform-delegated');
  headers.delete('x-platform-role');
  headers.delete('x-classroom-render-version');
  const serviceKey = process.env.PLATFORM_SERVICE_KEY;
  const supplied = request.headers.get('x-platform-service-key');
  const isService = Boolean(serviceKey && supplied === serviceKey);
  if (isService && request.nextUrl.pathname.startsWith('/api/internal/platform/')) {
    // These endpoints are called by the platform while it is authorizing a
    // browser request. Calling platform /authorize again here would recurse.
    // The service key proves the platform caller; each route checks this
    // middleware-injected marker before returning teacher-owned facts.
    headers.set('x-platform-delegated', 'true');
    headers.delete('x-platform-service-key');
    headers.delete('x-platform-subject');
    return NextResponse.next({ request: { headers } });
  }
  try {
    const authStartedAt = performance.now();
    const result = await authorizeTeacherRequest({
      baseUrl: `${(process.env.PLATFORM_AUTH_URL || '').replace(/\/$/, '')}/api/v1`,
      headers: { 'X-Teacher-Service-Key': serviceKey || '' },
      body: {
        cookie: request.cookies.get('agentedu_session')?.value,
        // Include the query string: the platform resolves classroom ownership
        // from `GET /api/classroom?id=...`, which carries the id in the query.
        path: `${request.nextUrl.pathname}${request.nextUrl.search}`,
        method: request.method,
        origin: request.headers.get('origin'),
        service_user_id: isService ? request.headers.get('x-platform-subject') : undefined,
      },
      signal: AbortSignal.timeout(5000),
      cache: 'no-store',
    });
    const authTiming = `platform-auth;dur=${(performance.now() - authStartedAt).toFixed(1)}`;
    if (!result.response) throw new Error('Platform authorization request failed');
    const status = result.response?.status ?? 503;
    if (!result.response?.ok) {
      if (status === 401 && !request.nextUrl.pathname.startsWith('/api/')) {
        return NextResponse.redirect(new URL('/login', process.env.PLATFORM_PUBLIC_URL || request.nextUrl.origin));
      }
      if (status >= 500) {
        return NextResponse.json({ success: false, error: '平台身份服务暂不可用，请稍后重试' }, { status: 503 });
      }
      // Pass the platform's specific rejection through: 401 未登录 / 403 无权限 /
      // 404 课程不存在 / 409 归属冲突 — never collapse them into one generic text.
      const detail = (result.error as { detail?: string } | undefined)?.detail;
      const fallback = status === 401 ? '请先登录平台' : '无权访问该资源';
      return NextResponse.json({ success: false, error: detail || fallback }, { status });
    }
    const principal = result.data;
    if (!principal?.userId) throw new Error('Platform authorization response is invalid');
    headers.set('x-platform-user-id', principal.userId);
    headers.set('x-platform-admin', principal.isAdmin ? 'true' : 'false');
    headers.set('x-platform-role', principal.role || 'teacher');
    if (isService) headers.set('x-platform-delegated', 'true');
    headers.delete('x-platform-service-key');
    headers.delete('x-platform-subject');
    const response = NextResponse.next({ request: { headers } });
    response.headers.set('Server-Timing', authTiming);
    return response;
  } catch (error) {
    log.error('Platform authorize call failed; failing closed:', error instanceof Error ? error.message : error);
    return NextResponse.json({ success: false, error: '平台身份服务暂不可用' }, { status: 503 });
  }
}

export function internalPlatformHeaders(userId: string): Record<string, string> {
  return process.env.PLATFORM_AUTH_ENABLED === 'true'
    ? { 'X-Platform-Service-Key': process.env.PLATFORM_SERVICE_KEY || '', 'X-Platform-Subject': userId }
    : {};
}
