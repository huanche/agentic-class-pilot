// Compile with contracts/tooling/tsconfig.test.json first. No real HTTP requests.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const { createClient } = require('../../.runtime/generated-client-js/teacher_platform_api/client/index.js');
const sdk = require('../../.runtime/generated-client-js/teacher_platform_api/sdk.gen.js');

const jsonResponse = (body, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { 'Content-Type': 'application/json' },
});

test('teacher authorization preserves wire body, service header and fetch safety options', async () => {
  let calls = 0;
  const client = createClient({ baseUrl: 'http://platform.invalid/api/v1', fetch: async (request) => {
    calls++;
    assert.equal(request.method, 'POST');
    assert.equal(new URL(request.url).pathname, '/api/v1/internal/teacher/authorize');
    assert.equal(request.headers.get('X-Teacher-Service-Key'), 'fixture-teacher-key');
    assert.equal(request.headers.get('Authorization'), null);
    assert.equal(request.redirect, 'error');
    assert.equal(request.cache, 'no-store');
    assert.deepEqual(await request.json(), { cookie: null, method: 'GET', path: '/api/classes' });
    return jsonResponse({ userId: 'fixture-user', role: 'teacher', future: true });
  } });
  const result = await sdk.authorizeTeacherRequest({ client,
    headers: { 'X-Teacher-Service-Key': 'fixture-teacher-key' }, cache: 'no-store', redirect: 'error',
    signal: AbortSignal.timeout(5000), body: { cookie: null, method: 'GET', path: '/api/classes' },
  });
  assert.equal(result.data.future, true);
  assert.equal(result.response.status, 200);
  assert.equal(calls, 1);
});

test('alias lookup encodes path parameter and preserves null alias', async () => {
  const client = createClient({ baseUrl: 'http://platform.invalid/api/v1', fetch: async (request) => {
    assert.equal(new URL(request.url).pathname, '/api/v1/internal/teacher/course-alias/course%2Ffixture');
    return jsonResponse({ legacyCourseId: null, platformCourseId: 'course-fixture' });
  } });
  const result = await sdk.resolveTeacherCourseAlias({ client, path: { course_id: 'course/fixture' } });
  assert.equal(result.data.legacyCourseId, null);
});

test('delegated identity and service secret remain distinct headers', async () => {
  const client = createClient({ baseUrl: 'http://platform.invalid/api/v1', fetch: async (request) => {
    assert.equal(request.headers.get('X-Platform-Subject'), 'fixture-user');
    assert.equal(request.headers.get('X-Teacher-Service-Key'), 'fixture-teacher-key');
    return jsonResponse({ members: [], courseId: 'fixture-course' });
  } });
  await sdk.getTeacherCourseMembers({ client, path: { course_id: 'fixture-course' }, headers: {
    'X-Platform-Subject': 'fixture-user', 'X-Teacher-Service-Key': 'fixture-teacher-key',
  } });
});

test('errors preserve status/body and do not retry writes', async () => {
  for (const status of [401, 403, 503, 500]) {
    let calls = 0;
    const client = createClient({ baseUrl: 'http://platform.invalid/api/v1', fetch: async () => {
      calls++;
      return jsonResponse({ detail: 'fixture' }, status);
    } });
    const result = await sdk.registerTeacherCourse({ client, body: { legacy_course_id: 'fixture', title: 'Fixture' } });
    assert.equal(result.data, undefined);
    assert.equal(result.response.status, status);
    assert.deepEqual(result.error, { detail: 'fixture' });
    assert.equal(calls, 1);
  }
});

test('transport failure is observable and no implicit retry occurs', async () => {
  let calls = 0;
  const failure = new TypeError('fixture offline');
  const client = createClient({ baseUrl: 'http://platform.invalid/api/v1', fetch: async () => {
    calls++;
    throw failure;
  } });
  const result = await sdk.resolveTeacherCourseAlias({ client, path: { course_id: 'fixture' } });
  assert.equal(result.error, failure);
  assert.equal(result.data, undefined);
  assert.equal(calls, 1);
});
