import test from "node:test";
import assert from "node:assert/strict";
import { createLearningClient } from "../../src/integration/session-commands.mjs";

function fixture(handler, existing = new Map()) {
  let id = 0;
  const calls = [];
  const storage = { getItem: key => existing.get(key) || null,
    setItem: (key, value) => existing.set(key, value), removeItem: key => existing.delete(key) };
  const request = async (path, method, body) => {
    calls.push({ path, method, body });
    if (path === "/session/resume") return {
      sessionId: "s", stateVersion: 5, contentGeneration: 2, messages: [], ...handler.initial };
    return handler.request(path, method, body);
  };
  const client = createLearningClient({ request, storage: () => storage,
    createId: () => `command-${++id}`, wait: async () => {}, pollLimit: 2 });
  return { client, calls, existing };
}

const view = { sessionId: "s", stateVersion: 7, contentGeneration: 2, messages: [{ text: "saved" }] };
const done = { status: "completed", commandId: "command-1", sessionView: view };
async function load(client) { return client.request("/session/resume", "POST", { launch_token: "ticket" }); }
async function send(client, text = "original answer") { return client.request("/session/s/message", "POST", { text }); }

test("network failure keeps the same command id, version and original answer on retry", async () => {
  let attempts = 0;
  const { client, calls } = fixture({ request: async () => {
    if (++attempts === 1) throw new TypeError("network unavailable");
    return done;
  } });
  await load(client);
  await assert.rejects(send(client));
  assert.deepEqual(await send(client), view);
  assert.deepEqual(calls[1].body, calls[2].body);
  assert.equal(calls[1].body.expectedStateVersion, 5);
  assert.equal(calls[1].body.launch_token, "ticket");
});

test("reload preserves the command after a lost response", async () => {
  const stored = new Map();
  const first = fixture({ request: async () => { throw new TypeError("response lost after commit"); } }, stored);
  await load(first.client);
  await assert.rejects(send(first.client));
  const original = first.calls[1].body;
  const second = fixture({ request: async () => done }, stored);
  assert.deepEqual(await load(second.client), view);
  assert.equal(second.calls[1].path, `/session/s/commands/${original.commandId}/status`);
  assert.equal(second.calls.filter(call => call.path.endsWith("/commands")).length, 0);
  assert.equal(stored.has("student_pending_command:s"), false);
});

test("failed evaluation keeps the accepted state and retries its original command", async () => {
  let attempts = 0;
  const { client, calls } = fixture({ request: async () => {
    if (++attempts === 1) {
      const error = new Error("model failure");
      error.commandResult = { status: "failed", sessionView: { ...view, stateVersion: 6, messages: [] },
        failure: { detail: "model failure", code: "MODEL_UNAVAILABLE" } };
      throw error;
    }
    return done;
  } });
  await load(client);
  await assert.rejects(send(client), error => error.sessionView.stateVersion === 6);
  await send(client);
  assert.deepEqual(calls[1].body, calls[2].body);
});

test("processing polls a status query without creating another command", async () => {
  const { client, calls } = fixture({ request: async path => path.endsWith("/status")
    ? done : { status: "processing", sessionView: { ...view, stateVersion: 6 } } });
  await load(client);
  assert.deepEqual(await send(client), view);
  assert.equal(calls.filter(call => call.path.endsWith("/commands")).length, 1);
  assert.equal(calls.at(-1).path, "/session/s/commands/command-1/status");
});

test("new device reconstructs the durable pending command from authenticated history", async () => {
  const submission = { commandId: "original-id", type: "submit_answer", payload: { text: "original answer" },
    expectedStateVersion: 4, contentGeneration: 2, status: "pending" };
  const { client, calls } = fixture({ initial: { pendingSubmission: submission }, request: async () => done });
  assert.deepEqual(await load(client), view);
  assert.equal(calls[1].body.commandId, "original-id");
  assert.equal(calls[1].body.expectedStateVersion, 4);
  assert.equal(calls[1].body.payload.text, "original answer");
});

test("version conflict refreshes the view and never automatically replays an answer", async () => {
  let attempts = 0;
  const { client, calls } = fixture({ request: async path => {
    if (path === "/session/s") return { ...view, stateVersion: 9 };
    if (++attempts === 1) {
      const error = new Error("conflict"); error.code = "VERSION_CONFLICT"; throw error;
    }
    return { ...done, sessionView: { ...view, stateVersion: 11 } };
  } });
  await load(client);
  await assert.rejects(send(client), error => error.sessionView.stateVersion === 9);
  assert.equal(attempts, 1);
  await send(client);
  assert.equal(calls.at(-1).body.expectedStateVersion, 9);
  assert.notEqual(calls[1].body.commandId, calls.at(-1).body.commandId);
});

test("an edited answer creates a new intent with the latest accepted version", async () => {
  const { client, calls } = fixture({ request: async () => {
    const error = new Error("model failure"); error.commandResult = {
      status: "failed", sessionView: { ...view, stateVersion: 6 }, failure: { detail: "failed" } };
    throw error;
  } });
  await load(client);
  await assert.rejects(send(client));
  await assert.rejects(send(client, "edited answer"));
  assert.notEqual(calls[1].body.commandId, calls[2].body.commandId);
  assert.equal(calls[2].body.expectedStateVersion, 6);
});

test("demo or pre-upgrade responses keep using existing endpoints", async () => {
  const { client, calls } = fixture({ initial: { stateVersion: undefined }, request: async () => view });
  await load(client);
  await send(client);
  assert.equal(calls.at(-1).path, "/session/s/message");
});

test("an old receipt cannot erase a newer pending submission from another device", async () => {
  let attempts = 0;
  const newer = { commandId: "other-device", type: "submit_answer", payload: { text: "next answer" },
    expectedStateVersion: 7, contentGeneration: 2, status: "processing" };
  const { client, calls, existing } = fixture({ request: async () => {
    if (++attempts === 1) throw new TypeError("response lost");
    if (attempts === 2) return { ...done, sessionView: { ...view, stateVersion: 8, pendingSubmission: newer } };
    return { ...done, sessionView: { ...view, stateVersion: 9 } };
  } });
  await load(client);
  await assert.rejects(send(client));
  await send(client);
  assert.equal(JSON.parse(existing.get("student_pending_command:s")).commandId, "other-device");
  await send(client, "next answer");
  assert.equal(calls.at(-1).body.commandId, "other-device");
  assert.equal(calls.at(-1).body.expectedStateVersion, 7);
});

test("new answers bind the task in the authoritative view", async () => {
  const { client, calls } = fixture({ initial: { currentTaskPublic: { taskId: "first-task" } },
    request: async () => ({ ...done, sessionView: { ...view, currentTaskPublic: { taskId: "next-task" } } }) });
  await load(client);
  await send(client);
  assert.equal(calls[1].body.payload.taskId, "first-task");
  await send(client, "next answer");
  assert.equal(calls[2].body.payload.taskId, "next-task");
});

test("a P2 pending answer keeps its original payload hash after P3 adds task metadata", async () => {
  const original = { commandId: "pre-p3", expectedStateVersion: 5, contentGeneration: 2,
    type: "submit_answer", payload: { text: "original answer" } };
  const stored = new Map([["student_pending_command:s", JSON.stringify(original)]]);
  const { client, calls } = fixture({ initial: { stateVersion: 6, currentTaskPublic: { taskId: "task" },
      pendingSubmission: { ...original, status: "failed" } }, request: async () => done }, stored);
  await load(client);
  await send(client);
  assert.deepEqual(calls.at(-1).body, { ...original, launch_token: "ticket" });
});

test("concurrent retries share one submission and one receipt polling chain", async () => {
  let resolve;
  const gate = new Promise(r => { resolve = r; });
  const { client, calls } = fixture({ request: async () => gate });
  await load(client);
  const first = send(client), second = send(client);
  resolve(done);
  await Promise.all([first, second]);
  assert.equal(calls.filter(c => c.path.endsWith("/commands")).length, 1);
});
