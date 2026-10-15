import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = (name) => readFileSync(new URL(`../src/legacy/${name}.js`, import.meta.url), "utf8");
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
const flush = () => new Promise((resolve) => setImmediate(resolve));

function apiHarness(fetch) {
  const timers = new Map();
  const ctx = vm.createContext({ process: { env: {} }, AbortController, fetch,
    setTimeout: (fn, ms) => { timers.set(fn, ms); return fn; }, clearTimeout: (fn) => timers.delete(fn) });
  vm.runInContext(source("api").replace(/export /g, ""), ctx);
  return { ctx, timers };
}

test("stalled reads and lesson controls time out and abort the connection", async () => {
  for (const method of ["GET", "POST"]) {
    let signal;
    const { ctx, timers } = apiHarness((url, options) => { signal = options.signal; return new Promise(() => {}); });
    const request = ctx.request(method, "/test");
    assert.equal([...timers.values()][0], method === "GET" ? 20000 : 120000);
    const check = assert.rejects(request, { code: "REQUEST_TIMEOUT" });
    [...timers.keys()][0]();
    await check;
    assert.equal(signal.aborted, true);
    assert.equal(timers.size, 0);
  }
});

test("deadline covers a stalled response body; normal errors retain status", async () => {
  const slow = apiHarness(async () => ({ ok: true, json: () => new Promise(() => {}) }));
  const request = slow.ctx.request("GET", "/test");
  await flush();
  const check = assert.rejects(request, { code: "REQUEST_TIMEOUT" });
  [...slow.timers.keys()][0]();
  await check;
  const failure = apiHarness(async () => ({ ok: false, status: 409, json: async () => ({ detail: "already running" }) }));
  await assert.rejects(failure.ctx.beginSession("test"), { status: 409, message: "already running" });
  assert.equal(failure.timers.size, 0);
});

function stageHarness(begin) {
  const nodes = new Map();
  function node(text = "") {
    return { textContent: text, children: [], handlers: {}, style: {}, parentElement: { hidden: false }, value: "",
      appendChild(child) { this.children.push(child); child.parent = this; },
      remove() { this.parent.children = this.parent.children.filter((child) => child !== this); },
      addEventListener(event, callback) { this.handlers[event] = callback; },
      replaceChildren() { this.children = []; } };
  }
  const find = (text) => { const walk = (n) => n.textContent === text ? n : n.children.map(walk).find(Boolean); return [...nodes.values()].map(walk).find(Boolean); };
  let phase = "intro", stateReads = 0, begins = 0;
  const ctx = { sessionId: "session-a", setStatus() {}, replySeenByPoll: () => false,
    getPhase: () => phase, applyServerTurn: (res) => { phase = res.hostPhase; } };
  const sandbox = vm.createContext({
    $: (id) => { if (id === "typing-row") return [...nodes.values()].flatMap((n) => n.children).find((n) => n.id === id); if (!nodes.has(id)) nodes.set(id, node()); return nodes.get(id); },
    el: (tag, cls, text) => node(text), icon: () => node(), renderInline: (s) => s, scrollToEnd() {},
    beginSession: () => { begins++; return begin(); },
    fetchSessionState: async () => { stateReads++; return { hostPhase: "guided_learning", status: "running" }; },
  });
  vm.runInContext(source("stage-class").replace(/import[\s\S]*?from "[^"]+";/g, "").replace(/export /g, ""), sandbox);
  const stage = sandbox.createStage(ctx); stage.mount();
  return { stage, nodes, find, ctx, start: () => nodes.get("btn-start").handlers.click(), counts: () => ({ begins, stateReads }) };
}

test("failed begin offers recovery; a running session is not started twice", async () => {
  const h = stageHarness(async () => { throw new Error("timeout"); });
  h.start(); await flush();
  assert.equal(h.nodes.get("composer-input").disabled, false);
  h.find("检查课堂状态并重试").handlers.click(); await flush();
  assert.deepEqual(h.counts(), { begins: 1, stateReads: 1 });
  assert.ok(h.find("开始播放教学视频"));
  assert.equal(h.find("检查课堂状态并重试"), undefined);
});

test("poll-confirmed guided learning adds exactly one play action despite a lost begin response", async () => {
  const pending = deferred(); const h = stageHarness(() => pending.promise);
  h.start();
  h.stage.receiveTurn({ hostPhase: "guided_learning" });
  h.stage.receiveTurn({ hostPhase: "guided_learning" });
  assert.equal(h.nodes.get("chat-log").children.filter((n) => n.children.some((c) => c.textContent === "开始播放教学视频")).length, 1);
  pending.reject(new Error("timeout")); await flush();
  assert.equal(h.find("检查课堂状态并重试"), undefined);
});

test("late begin response after switching lessons does not restore the old lesson", async () => {
  const pending = deferred(); const h = stageHarness(() => pending.promise);
  h.start(); h.stage.reset(); h.ctx.sessionId = "session-b";
  pending.resolve({ hostPhase: "guided_learning", message: { text: "old lesson" } }); await flush();
  assert.equal(h.find("开始播放教学视频"), undefined);
});

test("polling stays single-flight until both requests settle and drops stale session results", async () => {
  let reads = 0, applied = 0; const state = deferred(), messages = deferred();
  const ctx = vm.createContext({ sessionId: "a", location: { hash: "#/class/a" }, messageCursor: 0,
    parseHash: () => ({ name: "class" }), fetchSessionState: () => { reads++; return state.promise; },
    fetchSessionMessages: () => messages.promise, applyServerTurn: () => applied++, deliverServerMessage() {}, console: { warn() {} } });
  const app = source("app");
  vm.runInContext("var pollInFlight = false;\n" + app.slice(app.indexOf("function pollSession"), app.indexOf("function startPolling")), ctx);
  ctx.pollSession(); ctx.pollSession(); assert.equal(reads, 1);
  state.resolve({ hostPhase: "guided_learning" }); await flush();
  ctx.pollSession(); assert.equal(reads, 1);
  ctx.sessionId = "b"; messages.resolve({ messages: [], total: 0 }); await flush();
  assert.equal(applied, 0);
  ctx.pollSession(); await flush(); assert.equal(reads, 2);
});
