import test from "node:test";
import assert from "node:assert/strict";
import { requestSession } from "../../src/integration/session-http.mjs";

test("transport forwards cancellation and preserves durable failure receipts", async t => {
  const abort = new AbortController(); let request;
  const receipt = { commandId: "c", status: "failed", failure: { detail: "模型暂不可用", code: "MODEL_UNAVAILABLE" } };
  t.mock.method(globalThis, "fetch", async (url, options) => {
    request = { url, options };
    return { ok: false, status: 503, json: async () => receipt };
  });
  await assert.rejects(requestSession("/session/s/commands", "POST", { text: "原话" }, { signal: abort.signal }),
    error => error.status === 503 && error.commandResult === receipt);
  assert.equal(request.url, "/api/session/s/commands");
  assert.equal(request.options.signal, abort.signal);
  assert.deepEqual(JSON.parse(request.options.body), { text: "原话" });
});
