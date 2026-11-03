import { test } from 'node:test';
import assert from 'node:assert/strict';
import { prepareRecording, CAPTURE_READY_TIMEOUT_MS } from './readiness.mjs';

test('loading never transitions to recording before the real scene readiness resolves', async () => {
  let resolve;
  const loading = new Promise((r) => {
    resolve = r;
  });
  const phases = [];
  let inspected = false;
  const page = {
    evaluate: () => loading,
    locator: () => ({
      allTextContents: async () => {
        inspected = true;
        return [];
      },
    }),
  };
  const job = prepareRecording(page, 'scene', async (p) => {
    phases.push(p);
  });
  await new Promise((r) => setImmediate(r));
  assert.deepEqual(phases, ['loading']);
  assert.equal(inspected, false);
  resolve();
  await job;
  assert.deepEqual(phases, ['loading', 'recording']);
  assert.equal(inspected, true);
});
test('failed or timed out loading cannot start recording', async () => {
  const phases = [];
  const page = {
    evaluate: async () => {
      throw Error('原稿加载失败');
    },
    locator: () => ({ allTextContents: async () => [] }),
  };
  await assert.rejects(
    prepareRecording(page, 's', async (p) => phases.push(p)),
    /原稿加载失败/,
  );
  assert.deepEqual(phases, ['loading']);
  const stalled = { ...page, evaluate: () => new Promise(() => {}) };
  await assert.rejects(
    prepareRecording(stalled, 's', async () => {}, 5),
    /加载超时/,
  );
  assert(CAPTURE_READY_TIMEOUT_MS > 180000);
});
test('a visible page loading error blocks the recorder even if the ready promise resolved', async () => {
  const phases = [];
  const page = {
    evaluate: async () => {},
    locator: () => ({ allTextContents: async () => ['字体加载失败'] }),
  };
  await assert.rejects(
    prepareRecording(page, 's', async (p) => phases.push(p)),
    /字体加载失败/,
  );
  assert.deepEqual(phases, ['loading']);
});
