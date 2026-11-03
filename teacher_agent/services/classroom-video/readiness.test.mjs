import { test } from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { prepareRecording, prepareRecordingWithRetry, CAPTURE_READY_TIMEOUT_MS } from './readiness.mjs';

test('loading never transitions to recording before the real scene readiness resolves', async () => {
  let resolve;
  const loading = new Promise((r) => {
    resolve = r;
  });
  const phases = [];
  let inspected = false;
  const page = Object.assign(new EventEmitter(), {
    evaluate: () => loading,
    locator: () => ({
      allTextContents: async () => {
        inspected = true;
        return [];
      },
    }),
  });
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
  const page = Object.assign(new EventEmitter(), {
    evaluate: async () => {
      throw Error('原稿加载失败');
    },
    locator: () => ({ allTextContents: async () => [] }),
  });
  await assert.rejects(
    prepareRecording(page, 's', async (p) => phases.push(p)),
    /原稿加载失败/,
  );
  assert.deepEqual(phases, ['loading']);
  const stalled = Object.assign(new EventEmitter(), page, { evaluate: () => new Promise(() => {}) });
  await assert.rejects(
    prepareRecording(stalled, 's', async () => {}, 5),
    /加载超时/,
  );
  assert(CAPTURE_READY_TIMEOUT_MS > 180000);
});
test('a visible page loading error blocks the recorder even if the ready promise resolved', async () => {
  const phases = [];
  const page = Object.assign(new EventEmitter(), {
    evaluate: async () => {},
    locator: () => ({ allTextContents: async () => ['字体加载失败'] }),
  });
  await assert.rejects(
    prepareRecording(page, 's', async (p) => phases.push(p)),
    /字体加载失败/,
  );
  assert.deepEqual(phases, ['loading']);
});

test('engine startup exceptions reload once and still wait for the new scene before recording', async () => {
  const phases = []; let evaluations = 0, reloads = 0, resolve;
  const loaded = new Promise(r => { resolve = r; });
  const page = Object.assign(new EventEmitter(), {
    evaluate() {
      if (++evaluations === 1) queueMicrotask(() => {
        const error = new Error("Cannot read properties of undefined (reading 'extend')");
        error.stack += '\n at https://example.test/onlyoffice-engine/component.js:1:5';
        this.emit('pageerror', error);
      });
      return loaded;
    },
    reload: async () => { reloads++; },
    waitForFunction: async () => {},
    locator: () => ({ allTextContents: async () => [] }),
  });
  const job = prepareRecordingWithRetry(page, 's', async phase => phases.push(phase));
  await new Promise(r => setImmediate(r));
  assert.equal(reloads, 1); assert.deepEqual(phases, ['loading', 'loading']);
  resolve(); await job;
  assert.deepEqual(phases, ['loading', 'loading', 'recording']);
  assert.equal(page.listenerCount('pageerror'), 0);
});

test('a second engine startup exception fails without looping or recording', async () => {
  const phases = []; let reloads = 0;
  const page = Object.assign(new EventEmitter(), {
    evaluate() {
      queueMicrotask(() => {
        const error = new Error('engine crashed');
        error.stack += '\n at https://example.test/onlyoffice-engine/component.js:1:5';
        this.emit('pageerror', error);
      });
      return new Promise(() => {});
    },
    reload: async () => { reloads++; },
    waitForFunction: async () => {},
    locator: () => ({ allTextContents: async () => [] }),
  });
  await assert.rejects(prepareRecordingWithRetry(page, 's', async phase => phases.push(phase)), /初始化失败/);
  assert.equal(reloads, 1); assert.deepEqual(phases, ['loading', 'loading']);
  assert.equal(page.listenerCount('pageerror'), 0);
});
