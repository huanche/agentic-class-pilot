import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createBrowserSession, forwardTeacherCaptureRequest, renderVideoJob } from './jobs.mjs';

const clips = ['s1', 's2', 's3', 's4', 's5'].map((sceneId) => ({ sceneId }));

test('aborts a capture request when the teacher service disconnects instead of crashing the worker', async () => {
  let aborted = false;
  const route = {
    async fetch() {
      throw new Error('getaddrinfo EAI_AGAIN');
    },
    async abort() {
      aborted = true;
      throw new Error('context already closed');
    },
  };
  await forwardTeacherCaptureRequest(route, { url: 'http://teacher:3200/classroom-player/test' });
  assert.equal(aborted, true);
});

test('a failed page does not block later pages, and a single retry reuses four completed clips', async () => {
  const cache = new Set();
  const attempted = [];
  let latest;
  const services = {
    isReady: (clip) => cache.has(clip.sceneId),
    async capture(clip) {
      attempted.push(clip.sceneId);
      if (clip.sceneId === 's2' && attempted.indexOf('s3') === -1)
        throw new Error('original player could not initialize');
      cache.add(clip.sceneId);
    },
    report(state, progress) {
      latest = { state, ...progress };
    },
  };
  await renderVideoJob({ retries: new Set() }, clips, undefined, services);
  assert.deepEqual(
    attempted,
    clips.map(({ sceneId }) => sceneId),
  );
  assert.equal(latest.completed, 4);
  assert.equal(latest.state, 'failed');
  assert.deepEqual(latest.failedPages, { s2: 'original player could not initialize' });

  await renderVideoJob({ sceneId: 's2', retries: new Set() }, clips, latest, services);
  assert.deepEqual(attempted.slice(5), ['s2']);
  assert.deepEqual(latest, { state: 'ready', completed: 5, failedPages: {} });
});

test('prioritizes a teacher retry requested while a later page is recording', async () => {
  const job = { retries: new Set() };
  const attempted = [];
  await renderVideoJob(job, clips, undefined, {
    isReady: () => false,
    async capture({ sceneId }) {
      attempted.push(sceneId);
      if (attempted.length === 1) throw new Error('first attempt');
      if (sceneId === 's2') job.retries.add('s1');
    },
    report() {},
  });
  assert.deepEqual(attempted, ['s1', 's2', 's1', 's3', 's4', 's5']);
});

test('shares Chromium across isolated contexts and relaunches a disconnected process', async () => {
  let launches = 0;
  let connected = true;
  let contexts = 0;
  let closed = 0;
  const session = createBrowserSession(async () => {
    const launch = ++launches;
    return {
      isConnected: () => connected,
      newContext: async () => ({ launch, context: ++contexts }),
      close: async () => {
        closed++;
      },
    };
  });
  assert.deepEqual(await session.newContext(), { launch: 1, context: 1 });
  assert.deepEqual(await session.newContext(), { launch: 1, context: 2 });
  connected = false;
  assert.deepEqual(await session.newContext(), { launch: 2, context: 3 });
  await session.close();
  assert.equal(closed, 1);
});
