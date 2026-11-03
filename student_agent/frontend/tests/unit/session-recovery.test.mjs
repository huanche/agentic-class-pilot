import test from "node:test";
import assert from "node:assert/strict";
import { restoreStudentSession } from "../../src/integration/session-recovery.mjs";

const previous = { sessionId: "persisted", messages: [{ role: "student", text: "history" }] };

test("a new device selects a lesson and gets history without any browser cache", async () => {
  const calls = [];
  const result = await restoreStudentSession({
    launchToken: "new-login", lessonId: "lesson",
    api: async (...args) => { calls.push(args); return previous; },
  });
  assert.equal(result, previous);
  assert.deepEqual(calls, [["/session/resume", "POST", { launch_token: "new-login", lesson_id: "lesson" }]]);
});

test("old browser snapshot and session id cannot override the database response", async () => {
  const result = await restoreStudentSession({
    launchToken: "new-login", lessonId: "lesson", snapshot: "stale", sessionId: "old-id",
    api: async (path) => { assert.equal(path, "/session/resume"); return previous; },
  });
  assert.equal(result, previous);
});

for (const status of [401, 403, 409, 503]) {
  test(`HTTP ${status} preserves recovery failure instead of treating it as a new session`, async () => {
    const failure = Object.assign(new Error("recovery failed"), { status });
    let requests = 0;
    await assert.rejects(restoreStudentSession({
      launchToken: "token", lessonId: "lesson", snapshot: "preserve-this",
      api: async () => { requests++; throw failure; },
    }), error => error === failure);
    assert.equal(requests, 1);
  });
}

test("only missing history permits the normal new-lesson flow", async () => {
  const result = await restoreStudentSession({
    launchToken: "token", lessonId: "lesson",
    api: async () => { throw Object.assign(new Error("not found"), { status: 404 }); },
  });
  assert.equal(result, null);
});

test("catalog entry does not invent a lesson to restore", async () => {
  assert.equal(await restoreStudentSession({
    launchToken: "token", lessonId: "catalog", api: async () => assert.fail("not a selected lesson"),
  }), null);
});

test("missing platform identity never requests formal history by cached session id", async () => {
  assert.equal(await restoreStudentSession({
    lessonId: "lesson", sessionId: "somebody-elses-id", snapshot: "signed-but-not-authorized",
    api: async () => assert.fail("must enter through platform first"),
  }), null);
});

test("standalone demo can still restore its signed local snapshot", async () => {
  assert.equal(await restoreStudentSession({
    demo: true, snapshot: "demo-snapshot",
    api: async (...args) => {
      assert.deepEqual(args, ["/session/browser-restore", "POST", { snapshot: "demo-snapshot" }]);
      return previous;
    },
  }), previous);
});
