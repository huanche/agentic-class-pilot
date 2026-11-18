import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';
import { GET, POST, PUT } from '@/app/api/classes/[courseId]/student-profiles/route';

const fetchMock = vi.fn();
const context = { params: Promise.resolve({ courseId: 'course-1' }) };
const request = (method = 'GET', body?: BodyInit) => new NextRequest('http://teacher.test/api/classes/course-1/student-profiles', {
  method, body, headers: { 'x-platform-user-id': 'teacher-1' },
});
beforeEach(() => {
  vi.stubEnv('PLATFORM_AUTH_ENABLED', 'true');
  vi.stubEnv('PLATFORM_AUTH_URL', 'http://platform.test:8080');
  vi.stubEnv('PLATFORM_SERVICE_KEY', 'test-service-key');
  vi.stubGlobal('fetch', fetchMock);
  vi.spyOn(console, 'error').mockImplementation(() => {});
  fetchMock.mockReset();
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

it('passes course identity and confirmed entries to the platform', async () => {
  fetchMock.mockResolvedValueOnce(Response.json({ entries: [] }));
  const body = JSON.stringify({ entries: [], previous: [] });
  expect((await PUT(request('PUT', body), context)).status).toBe(200);
  expect(fetchMock).toHaveBeenCalledWith('http://platform.test:8080/api/v1/internal/teacher/courses/course-1/student-profiles',
    expect.objectContaining({ method: 'PUT', body, headers: {
      'X-Teacher-Service-Key': 'test-service-key', 'X-Platform-Subject': 'teacher-1', 'Content-Type': 'application/json',
    } }));
});
it('does not query student data without teacher identity', async () => {
  expect((await GET(new NextRequest('http://teacher.test/'), context)).status).toBe(401);
  expect(fetchMock).not.toHaveBeenCalled();
});
it('checks course ownership before processing a PDF', async () => {
  fetchMock.mockResolvedValueOnce(Response.json({ detail: '无权访问课程' }, { status: 403 }));
  expect((await POST(request('POST', 'invalid form'), context)).status).toBe(403);
});
it('rejects non-PDF uploads without writing records', async () => {
  fetchMock.mockResolvedValueOnce(Response.json({ entries: [], members: [] }));
  const form = new FormData(); form.append('file', new File(['text'], 'roster.txt'));
  expect((await POST(request('POST', form), context)).status).toBe(422);
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(fetchMock.mock.calls[0][1].method).toBe('GET');
});
it.each([409, 422, 503])('keeps save failures visible (%s)', async status => {
  fetchMock.mockResolvedValueOnce(Response.json({ detail: '保存失败' }, { status }));
  expect((await PUT(request('PUT', '{}'), context)).status).toBe(status);
});
