import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

import { platformCourseMembers } from '@/lib/server/platform-course-members';

const fetchMock = vi.fn();
const request = () => new NextRequest('http://teacher.test/api/classes/course-1', {
  headers: { 'x-platform-user-id': 'teacher-1' },
});

beforeEach(() => {
  vi.stubEnv('PLATFORM_AUTH_ENABLED', 'true');
  vi.stubEnv('PLATFORM_AUTH_URL', 'http://platform.test:8080');
  vi.stubEnv('PLATFORM_SERVICE_KEY', 'test-service-key');
  vi.stubEnv('TEACHER_PLATFORM_CLIENT_MODE', 'generated');
  vi.stubGlobal('fetch', fetchMock);
  fetchMock.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

it('uses the generated roster contract with delegated identity', async () => {
  fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({
    courseId: 'course-1', members: [{ studentId: 'student-1', name: 'Student' }],
  }), { status: 200, headers: { 'content-type': 'application/json' } }));

  expect(await platformCourseMembers(request(), 'course-1')).toEqual([
    { studentId: 'student-1', name: 'Student' },
  ]);
  expect(fetchMock).toHaveBeenCalledTimes(1);
  const sent = fetchMock.mock.calls[0][0] as Request;
  expect(sent.url).toBe('http://platform.test:8080/api/v1/internal/teacher/courses/course-1/members');
  expect(sent.method).toBe('GET');
  expect(sent.headers.get('X-Teacher-Service-Key')).toBe('test-service-key');
  expect(sent.headers.get('X-Platform-Subject')).toBe('teacher-1');
  expect(sent.redirect).toBe('error');
});

it('does not treat a platform rejection as an empty roster', async () => {
  fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'forbidden' }), {
    status: 403, headers: { 'content-type': 'application/json' },
  }));
  await expect(platformCourseMembers(request(), 'course-1')).rejects.toThrow('forbidden');
});

it('keeps the existing fetch path when generated mode is off', async () => {
  vi.stubEnv('TEACHER_PLATFORM_CLIENT_MODE', 'legacy');
  fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ members: [] }), {
    status: 200, headers: { 'content-type': 'application/json' },
  }));
  expect(await platformCourseMembers(request(), 'course-1')).toEqual([]);
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(fetchMock.mock.calls[0][0]).toBe(
    'http://platform.test:8080/api/v1/internal/teacher/courses/course-1/members',
  );
});
