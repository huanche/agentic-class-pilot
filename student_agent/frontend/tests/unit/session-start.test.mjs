import assert from 'node:assert/strict';
import { beforeEach, test } from 'node:test';
import { startSession, initializePlatformSession } from '../../src/legacy/api.js';
import { shouldRenewSession } from '../../src/legacy/session-continuity.js';

beforeEach(() => {
  const values = new Map();
  globalThis.sessionStorage = { getItem: k => values.get(k) || null, setItem: (k, v) => values.set(k, v) };
  globalThis.window = { __studentLaunchToken: 'expired', location: { hash: '#/course/11111111-1111-4111-8111-111111111111' }, localStorage: {getItem: () => null} };
});

test('an expired entry token is renewed through the authenticated platform entry', async () => {
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    if (calls.length === 1) return Response.json({ detail: '令牌已过期' }, {status:401});
    if (calls.length === 2) return Response.json({ launchToken: 'renewed' });
    return Response.json({ session_id:'same-session', status:'running', phase:'guided_learning' });
  };
  const result = await startSession({ sessionId:'same-session', lessonId:'lesson-1' });
  assert.equal(result.sessionId, 'same-session');
  assert.equal(calls[1].url, '/api/v1/courses/11111111-1111-4111-8111-111111111111/student-workspace');
  assert.equal(calls[1].options.credentials, 'include');
  assert.equal(JSON.parse(calls[2].options.body).launch_token, 'renewed');
  assert.equal(JSON.parse(calls[2].options.body).session_id, 'same-session');
});

test('a denied renewal is surfaced without creating another session or bypassing login', async () => {
  let calls = 0;
  globalThis.fetch = async () => { calls++; return Response.json({detail:'登录已过期'}, {status:401}); };
  await assert.rejects(startSession({sessionId:'old'}), /登录已过期/);
  assert.equal(calls, 2);
});

test('refresh reuses the catalog session and concurrent boot calls share one start', async () => {
  sessionStorage.setItem('__studentSessionId', 'saved-catalog');
  const bodies = [];
  globalThis.fetch = async (_url, options) => {
    bodies.push(JSON.parse(options.body));
    return Response.json({ session_id: 'saved-catalog', platform: {userId:'user', courseId:'course'} });
  };
  const results = await Promise.all([initializePlatformSession(), initializePlatformSession()]);
  assert.equal(bodies.length, 1);
  assert.equal(bodies[0].session_id, 'saved-catalog');
  assert.equal(results[1].sessionId, 'saved-catalog');
  assert.equal(JSON.parse(sessionStorage.getItem('__studentPlatform')).userId, 'user');
});

test('a course/account conflict creates a fresh catalog session without changing the old one', async () => {
  sessionStorage.setItem('__studentSessionId', 'old-account');
  const bodies = [];
  globalThis.fetch = async (_url, options) => {
    bodies.push(JSON.parse(options.body));
    return bodies.length === 1 ? Response.json({detail:'conflict'}, {status:409}) : Response.json({session_id:'new-account'});
  };
  await initializePlatformSession();
  assert.equal(bodies[0].session_id, 'old-account');
  assert.equal(bodies[1].session_id, undefined);
  assert.equal(sessionStorage.getItem('__studentSessionId'), 'new-account');
});

test('an old running session survives a new tab; only a finished lesson is restarted', () => {
  assert.equal(shouldRenewSession({status:'running',updated_at:1}), false);
  assert.equal(shouldRenewSession({status:'idle'}), false);
  assert.equal(shouldRenewSession({status:'ended'}), true);
});
