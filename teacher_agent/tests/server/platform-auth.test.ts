import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

import { internalPlatformHeaders, platformMiddleware } from '@/lib/server/platform-auth';

const AUTH_URL = 'http://platform.test:8080';
const SERVICE_KEY = 'test-service-key';

interface TestRequestOptions {
  method?: string;
  headers?: Record<string, string>;
}

function makeRequest(path: string, options: TestRequestOptions = {}): NextRequest {
  return new NextRequest(`http://teacher.test:3200${path}`, {
    method: options.method,
    headers: options.headers,
  });
}

function authorizeResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

describe('platformMiddleware', () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    process.env.PLATFORM_AUTH_URL = AUTH_URL;
    process.env.PLATFORM_PUBLIC_URL = 'http://platform.test:8080';
    process.env.PLATFORM_SERVICE_KEY = SERVICE_KEY;
    vi.stubGlobal('fetch', fetchMock);
    fetchMock.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    delete process.env.PLATFORM_AUTH_URL;
    delete process.env.PLATFORM_PUBLIC_URL;
    delete process.env.PLATFORM_SERVICE_KEY;
  });

  it('passes /api/health through without contacting the platform', async () => {
    const response = await platformMiddleware(makeRequest('/api/health'));
    expect(response.headers.get('x-middleware-override-headers')).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('returns 401 JSON for anonymous API requests', async () => {
    fetchMock.mockResolvedValueOnce(authorizeResponse({ detail: 'unauthenticated' }, 401));
    const response = await platformMiddleware(makeRequest('/api/course-space'));
    expect(response.status).toBe(401);
    await expect(response.json()).resolves.toMatchObject({ success: false });
  });

  it('redirects anonymous page requests to the platform login', async () => {
    fetchMock.mockResolvedValueOnce(authorizeResponse({ detail: 'unauthenticated' }, 401));
    const response = await platformMiddleware(makeRequest('/course-space'));
    expect(response.status).toBe(307);
    expect(response.headers.get('location')).toBe('http://platform.test:8080/login');
  });

  it('propagates 403 for authenticated but unauthorized requests', async () => {
    fetchMock.mockResolvedValueOnce(authorizeResponse({ detail: 'Teacher role required' }, 403));
    const response = await platformMiddleware(makeRequest('/api/course-space'));
    expect(response.status).toBe(403);
  });

  it('sends cookie, method, origin and the full path with query to the platform', async () => {
    fetchMock.mockResolvedValueOnce(authorizeResponse({ userId: 'user-1', isAdmin: false }));
    const request = makeRequest('/api/classroom?id=cls-1', {
      method: 'GET',
      headers: { cookie: 'agentedu_session=session-token', origin: 'http://teacher.test:3200' },
    });
    const response = await platformMiddleware(request);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${AUTH_URL}/api/v1/internal/teacher/authorize`);
    expect(init.headers['X-Teacher-Service-Key']).toBe(SERVICE_KEY);
    expect(JSON.parse(String(init.body))).toEqual({
      cookie: 'session-token',
      path: '/api/classroom?id=cls-1',
      method: 'GET',
      origin: 'http://teacher.test:3200',
      service_user_id: undefined,
    });
    expect(response.headers.get('x-middleware-override-headers')).toContain('x-platform-user-id');
  });

  it('strips spoofed identity and service headers, then injects the platform principal', async () => {
    fetchMock.mockResolvedValueOnce(authorizeResponse({ userId: 'real-user', isAdmin: true }));
    const request = makeRequest('/api/course-space', {
      headers: {
        'x-platform-user-id': 'attacker',
        'x-platform-admin': 'true',
        'x-platform-delegated': 'true',
        'x-platform-service-key': 'not-the-key',
        'x-platform-subject': 'attacker',
      },
    });
    const response = await platformMiddleware(request);
    const overrideList = (response.headers.get('x-middleware-override-headers') || '').toLowerCase();
    expect(overrideList).toContain('x-platform-user-id');
    expect(overrideList).toContain('x-platform-admin');
    const body = JSON.parse(String(fetchMock.mock.calls[0][1].body));
    expect(body.service_user_id).toBeUndefined();
  });

  it('delegates service calls and marks them as platform-initiated', async () => {
    fetchMock.mockResolvedValueOnce(authorizeResponse({ userId: 'delegated-user', isAdmin: false }));
    const request = makeRequest('/api/course-space', {
      method: 'POST',
      headers: { 'x-platform-service-key': SERVICE_KEY, 'x-platform-subject': 'platform-course-owner' },
    });
    const response = await platformMiddleware(request);
    const body = JSON.parse(String(fetchMock.mock.calls[0][1].body));
    expect(body.service_user_id).toBe('platform-course-owner');
    const overrideList = (response.headers.get('x-middleware-override-headers') || '').toLowerCase();
    expect(overrideList).toContain('x-platform-delegated');
  });

  it('fails closed with 503 when the platform identity service is unreachable', async () => {
    fetchMock.mockRejectedValueOnce(new TypeError('network down'));
    const response = await platformMiddleware(makeRequest('/api/course-space'));
    expect(response.status).toBe(503);
    await expect(response.json()).resolves.toMatchObject({ success: false, error: '平台身份服务暂不可用' });
  });
});

describe('internalPlatformHeaders', () => {
  afterEach(() => {
    delete process.env.PLATFORM_AUTH_ENABLED;
    delete process.env.PLATFORM_SERVICE_KEY;
  });

  it('returns service headers only in platform mode', () => {
    process.env.PLATFORM_AUTH_ENABLED = 'false';
    expect(internalPlatformHeaders('user-1')).toEqual({});
    process.env.PLATFORM_AUTH_ENABLED = 'true';
    process.env.PLATFORM_SERVICE_KEY = SERVICE_KEY;
    expect(internalPlatformHeaders('user-1')).toEqual({
      'X-Platform-Service-Key': SERVICE_KEY,
      'X-Platform-Subject': 'user-1',
    });
  });
});
