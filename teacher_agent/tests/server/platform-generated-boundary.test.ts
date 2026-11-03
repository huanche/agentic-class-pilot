import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

import { platformEnrollmentCode } from '@/lib/server/platform-enrollment';
import { registerCourseWithPlatform, resolveLegacyCourseId } from '@/lib/server/platform-course-bridge';
import { fetchPlatformUserModelConfig } from '@/lib/server/platform-user-model-config';

const COURSE_ID = '11111111-1111-1111-1111-111111111111';
const fetchMock = vi.fn();

function ok(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200, headers: { 'content-type': 'application/json' },
  });
}

describe('generated platform boundary', () => {
  beforeEach(() => {
    vi.stubEnv('PLATFORM_AUTH_ENABLED', 'true');
    vi.stubEnv('PLATFORM_AUTH_URL', 'http://platform.test');
    vi.stubEnv('PLATFORM_SERVICE_KEY', 'test-key');
    vi.stubGlobal('fetch', fetchMock);
    fetchMock.mockReset();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it('registers a course with the documented request body', async () => {
    fetchMock.mockResolvedValueOnce(ok({ id: COURSE_ID }));
    await registerCourseWithPlatform({ id: COURSE_ID, teacherId: 'teacher-1', title: 'Course' });
    const request = fetchMock.mock.calls[0][0] as Request;
    expect(request.url).toBe('http://platform.test/api/v1/internal/teacher/courses');
    expect(request.headers.get('X-Teacher-Service-Key')).toBe('test-key');
    await expect(request.json()).resolves.toEqual({ course_id: COURSE_ID, teacher_id: 'teacher-1', title: 'Course' });
  });

  it('resolves a historical course alias through the documented path', async () => {
    fetchMock.mockResolvedValueOnce(ok({ platformCourseId: COURSE_ID, legacyCourseId: 'legacy-1' }));
    expect(await resolveLegacyCourseId(COURSE_ID)).toBe('legacy-1');
    expect((fetchMock.mock.calls[0][0] as Request).url).toBe(
      `http://platform.test/api/v1/internal/teacher/course-alias/${COURSE_ID}`,
    );
  });

  it('passes the delegated teacher identity for enrollment reads', async () => {
    fetchMock.mockResolvedValueOnce(ok({ courseId: COURSE_ID, enrollCode: 'ABC123' }));
    const request = new NextRequest('http://teacher.test/api/classes', {
      headers: { 'x-platform-user-id': 'teacher-1' },
    });
    const response = await platformEnrollmentCode(request, COURSE_ID);
    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({ courseId: COURSE_ID, enrollCode: 'ABC123' });
    const sent = fetchMock.mock.calls[0][0] as Request;
    expect(sent.url).toBe(`http://platform.test/api/v1/internal/teacher/courses/${COURSE_ID}/enrollment`);
    expect(sent.headers.get('X-Platform-Subject')).toBe('teacher-1');
  });

  it('reads per-user model settings from the generated route', async () => {
    fetchMock.mockResolvedValueOnce(ok({ llm: { model: 'test-model' } }));
    expect(await fetchPlatformUserModelConfig('model-user-1')).toEqual({ llm: { model: 'test-model' } });
    expect((fetchMock.mock.calls[0][0] as Request).url).toBe(
      'http://platform.test/api/v1/internal/user/model-user-1/model-config',
    );
  });
});
