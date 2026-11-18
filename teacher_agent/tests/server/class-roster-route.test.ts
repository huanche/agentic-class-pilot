import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';
import { GET } from '@/app/api/classes/[courseId]/roster/route';

const fetchMock = vi.fn();
const request = (query = '') => GET(new NextRequest(`http://teacher.test/api/classes/course-1/roster${query}`, {
  headers: { 'x-platform-user-id': 'teacher-1' },
}), { params: Promise.resolve({ courseId: 'course-1' }) });

beforeEach(() => {
  vi.stubEnv('PLATFORM_AUTH_ENABLED', 'true');
  vi.stubEnv('PLATFORM_AUTH_URL', 'http://platform.test:8080');
  vi.stubEnv('PLATFORM_SERVICE_KEY', 'test-service-key');
  vi.stubGlobal('fetch', fetchMock);
  vi.spyOn(console, 'error').mockImplementation(() => {});
  fetchMock.mockReset();
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

it('passes real roster data and the selected student with delegated teacher identity', async () => {
  const data = { lessons: [], students: [{ studentId: 'student-1', name: '张同学' }], assessments: [] };
  fetchMock.mockResolvedValueOnce(Response.json(data));
  const response = await request('?student=student-1');
  expect(response.status).toBe(200);
  expect(await response.json()).toEqual(data);
  expect(fetchMock.mock.calls[0][0].toString()).toBe(
    'http://platform.test:8080/api/v1/internal/teacher/courses/course-1/roster-progress?student_id=student-1');
  expect(fetchMock.mock.calls[0][1].headers).toEqual({
    'X-Teacher-Service-Key': 'test-service-key', 'X-Platform-Subject': 'teacher-1',
  });
});

it.each(['', '<html>Not Found</html>', JSON.stringify({ detail: 'Not Found' })])(
  'does not claim student data is missing when the upstream route is unavailable (%s)', async body => {
    fetchMock.mockResolvedValueOnce(new Response(body, { status: 404 }));
    const response = await request();
    expect(response.status).toBe(503);
    expect(await response.json()).toMatchObject({ code: 'LEARNING_SERVICE_UNAVAILABLE' });
    expect(console.error).toHaveBeenCalledWith('读取班级学情失败', expect.objectContaining({ upstreamStatus: 404 }));
  },
);

it.each([
  ['Course not found', 'COURSE_NOT_FOUND'],
  ['课程不存在', 'COURSE_NOT_FOUND'],
  ['该学生未加入本课程', 'STUDENT_NOT_ENROLLED'],
])('preserves confirmed resource errors: %s', async (detail, code) => {
  fetchMock.mockResolvedValueOnce(Response.json({ detail }, { status: 404 }));
  const response = await request('?student=student-1');
  expect(response.status).toBe(404);
  expect(await response.json()).toMatchObject({ code });
});

it.each([401, 403, 500, 503])('keeps upstream failures visible without exposing internals (%i)', async status => {
  fetchMock.mockResolvedValueOnce(Response.json({ detail: 'private backend error' }, { status }));
  const response = await request();
  expect(response.status).toBe(status < 500 ? status : 503);
  expect(await response.text()).not.toContain('private backend error');
});

it('does not call the platform for an anonymous teacher request', async () => {
  const response = await GET(new NextRequest('http://teacher.test/api/classes/course-1/roster'), {
    params: Promise.resolve({ courseId: 'course-1' }),
  });
  expect(response.status).toBe(401);
  expect(fetchMock).not.toHaveBeenCalled();
});

it('reports transport errors as unavailable instead of returning an empty roster', async () => {
  fetchMock.mockRejectedValueOnce(new Error('connection refused'));
  expect((await request()).status).toBe(503);
});
