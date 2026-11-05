import test from "node:test";
import assert from "node:assert/strict";
import { createLearningSession } from "../../src/integration/learning-session.mjs";
import { createSessionBrowser } from "../../src/integration/session-browser.mjs";

function deferred() { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; }
const courses = [{ id: "c", title: "课程", lessons: [
  { id: "L1", title: "课时一", classroomId: "room", playerUrl: "https://example.test/player" },
  { id: "L2", title: "课时二", playerUrl: "https://example.test/other" }] }];
const actions = ["submit_answer", "request_help", "ask_question", "pause", "finish"];
function fixture(t, { handler, state = {}, stored = new Map(), commandOptions = {} } = {}) {
  stored.set("student_last_course:u", "c");
  const storage = { getItem: key => stored.get(key) || null,
    setItem: (key, value) => stored.set(key, value), removeItem: key => stored.delete(key) };
  const calls = [], updates = [], timers = new Map(); let timerId = 0, commandId = 0;
  let server = { sessionId: "s", userId: "u", lessonId: "L1", courses, phase: "discussion", stateVersion: 5,
    contentGeneration: 0, flowVersion: "dynamic_dialogue_v1", activityStatus: "active", agentStage: "tutoring",
    currentTaskPublic: { taskId: "task-1" }, allowedCommands: actions, preparation: "ready", messages: [], ...state };
  const request = async (path, method, body, options = {}) => {
    calls.push({ path, method, body, signal: options.signal });
    if (handler) {
      const result = await handler({ path, method, body, options, server, set: value => { server = value; } });
      if (result !== undefined) return result;
    }
    if (path === "/session/identity") return { userId: "u", csrfToken: "csrf" };
    if (path === "/session/platform-entry") return { platformUrl: "https://platform.test" };
    if (path === "/session/start") return { sessionId: "catalog", userId: "u", phase: "idle", courses,
      stateVersion: 0, messages: [], browserCourseKey: "u:c" };
    if (path === "/session/resume" || path === "/session/s") return structuredClone(server);
    if (path === "/session/s/commands") {
      if (body.type === "pause") server = { ...server, activityStatus: "paused", allowedCommands: ["resume_activity", "finish"] };
      else if (body.type === "resume_activity") server = { ...server, activityStatus: "active", allowedCommands: actions };
      else if (body.type === "finish") server = { ...server, phase: "done", agentStage: "wrapup",
        allowedCommands: ["continue_after_class", "reset_lesson", "finish"] };
      else server = { ...server, messages: [...server.messages, { role: "student", text: body.payload.text }] };
      server.stateVersion += 2;
      return { commandId: body.commandId, status: "completed", sessionView: structuredClone(server) };
    }
    throw new Error(`Unexpected request: ${path}`);
  };
  const controller = createLearningSession({ request, storage: () => storage,
    setTimer: callback => { timers.set(++timerId, callback); return timerId; }, clearTimer: id => timers.delete(id),
    commandOptions: { createId: () => `cmd-${++commandId}`, wait: async () => {}, pollLimit: 2, ...commandOptions } });
  const unsubscribe = controller.subscribe(view => updates.push(view));
  t.after(unsubscribe);
  return { controller, calls, updates, timers, stored, storage, unsubscribe,
    set: patch => { server = { ...server, ...patch }; },
    start: async () => { await controller.initialize({ url: "https://app.test/app/" }); await controller.loadLesson(courses[0].lessons[0]); } };
}

test("one Interface loads authenticated history and submits structured help with the current task", async t => {
  const f = fixture(t); await f.start();
  await f.controller.dispatch({ type: "request_help", text: "请给提示" });
  const call = f.calls.at(-1);
  assert.equal(call.body.type, "request_help");
  assert.deepEqual(call.body.payload, { text: "请给提示", taskId: "task-1" });
  assert.equal(call.body.expectedStateVersion, 5);
  assert.equal(f.controller.getView().messages[0].text, "请给提示");
  assert.equal(f.controller.getView().busy, false);
});

test("pause and resume preserve the task and reject teaching input while paused", async t => {
  const f = fixture(t); await f.start();
  await f.controller.dispatch({ type: "pause" });
  const before = f.calls.length;
  await assert.rejects(f.controller.dispatch({ type: "submit_answer", text: "不能推进" }));
  assert.equal(f.calls.length, before);
  assert.equal(f.controller.getView().currentTaskPublic.taskId, "task-1");
  await f.controller.dispatch({ type: "resume_activity" });
  assert.equal(f.controller.getView().activityStatus, "active");
  assert.deepEqual(f.calls.at(-1).body.payload, {});
});

test("help retry retains the original command identity and task after a lost response", async t => {
  let attempt = 0;
  const f = fixture(t, { handler: ({ path }) => {
    if (path === "/session/s/commands" && ++attempt === 1) throw new Error("lost response");
  } }); await f.start();
  await assert.rejects(f.controller.dispatch({ type: "request_help", text: "举一个例子" }));
  await f.controller.dispatch({ type: "request_help", text: "举一个例子" });
  const sends = f.calls.filter(c => c.path.endsWith("/commands"));
  assert.deepEqual(sends[0].body, sends[1].body);
  assert.equal(f.stored.has("student_pending_command:u:s"), false);
});

test("status polling is single-flight and unsubscription aborts waiting without deleting the pending command", async t => {
  const gate = deferred();
  const f = fixture(t, { commandOptions: { wait: () => gate.promise }, handler: ({ path, server }) => {
    if (path === "/session/s/commands") return { commandId: "cmd-1", status: "processing", sessionView: server };
  } }); await f.start();
  const task = f.controller.dispatch({ type: "request_help", text: "提示" });
  await new Promise(setImmediate);
  const before = f.updates.length;
  f.unsubscribe(); gate.resolve(); await task;
  assert.equal(f.updates.length, before);
  assert.equal(f.timers.size, 0);
  assert.equal(JSON.parse(f.stored.get("student_pending_command:u:s")).commandId, "cmd-1");
  assert.equal(f.calls.filter(c => c.path.endsWith("/status")).length, 0);
});

test("one refresh loop sees another device pause, resume and finish with no command submission", async t => {
  const f = fixture(t); await f.start();
  assert.equal(f.timers.size, 1);
  const before = f.calls.length;
  f.set({ stateVersion: 7, activityStatus: "paused", allowedCommands: ["resume_activity", "finish"] });
  await f.controller.refresh();
  assert.equal(f.controller.getView().activityStatus, "paused");
  f.set({ stateVersion: 9, activityStatus: "active", allowedCommands: actions });
  await f.controller.refresh();
  f.set({ stateVersion: 11, phase: "done", agentStage: "wrapup" });
  await f.controller.refresh();
  assert.equal(f.controller.getView().screen, "done");
  assert.ok(f.calls.slice(before).every(c => c.path === "/session/s"));
  assert.equal(f.timers.size, 1);
});

test("overlapping refresh calls share the same read and lower versions cannot roll the task back", async t => {
  const gate = deferred(); let reads = 0;
  const f = fixture(t, { handler: ({ path }) => { if (path === "/session/s") { reads++; return gate.promise; } } });
  await f.start();
  const first = f.controller.refresh(), second = f.controller.refresh();
  gate.resolve({ ...f.controller.getView(), stateVersion: 3, currentTaskPublic: { taskId: "stale" } });
  await Promise.all([first, second]);
  assert.equal(reads, 1);
  assert.equal(f.controller.getView().currentTaskPublic.taskId, "task-1");
});

test("switching lessons ignores late history and storage updates from the old selection", async t => {
  const gate = deferred(); let count = 0;
  const f = fixture(t, { handler: ({ path, body, server }) => {
    if (path === "/session/resume" && ++count === 1) return gate.promise;
    if (path === "/session/resume") return { ...server, sessionId: "second", lessonId: body.lesson_id };
  } });
  await f.controller.initialize({ url: "https://app.test/app/" });
  const old = f.controller.loadLesson(courses[0].lessons[0]);
  await f.controller.loadLesson(courses[0].lessons[1]);
  gate.resolve({ sessionId: "first", lessonId: "L1", phase: "discussion", courses,
    browserKey: "u:c:L1", browserSnapshot: "obsolete", messages: [] });
  await old;
  assert.equal(f.controller.getView().lesson.id, "L2");
  assert.equal(f.stored.get("student_browser_locator:u:c:L1"), undefined);
});

test("preparation refresh and replay refresh preserve player identity and presentation", async t => {
  const f = fixture(t, { state: { phase: "video", preparation: "pending" } }); await f.start();
  const lesson = f.controller.getView().lesson;
  f.set({ stateVersion: 6, preparation: "ready" }); await f.controller.refresh();
  assert.equal(f.controller.getView().lesson, lesson);
  assert.equal(f.controller.getView().preparation, "ready");
  f.set({ phase: "done", stateVersion: 8 }); await f.controller.refresh();
  await f.controller.dispatch({ type: "replay" }); await f.controller.refresh();
  assert.equal(f.controller.getView().screen, "replay");
  assert.equal(f.controller.getView().lesson, lesson);
});

test("postclass is presentation under done and refreshing cannot move it back to classroom", async t => {
  const f = fixture(t, { state: { phase: "done", allowedCommands: ["continue_after_class"] },
    handler: ({ path, server }) => path.endsWith("/commands") ? { commandId: "cmd-1", status: "completed",
      sessionView: { ...server, stateVersion: 7, postclassStage: "open", allowedCommands: ["postclass_answer", "pause", "finish"] } } : undefined });
  await f.start(); await f.controller.dispatch({ type: "continue_after_class" });
  f.set({ stateVersion: 7, postclassStage: "open" }); await f.controller.refresh();
  assert.equal(f.controller.getView().phase, "done");
  assert.equal(f.controller.getView().screen, "postclass");
});

test("transient polling failure keeps the learning view and schedules recovery", async t => {
  let failed = false;
  const f = fixture(t, { handler: ({ path }) => { if (path === "/session/s" && !failed) { failed = true; throw new Error("offline"); } } });
  await f.start(); await f.controller.refresh();
  assert.equal(f.controller.getView().screen, "discussion");
  assert.equal(f.controller.getView().connectionError, "offline");
  assert.equal(f.timers.size, 1);
  await f.controller.refresh();
  assert.equal(f.controller.getView().connectionError, "");
});

test("authentication recovery failures are not treated as empty history", async t => {
  const f = fixture(t, { handler: ({ path }) => {
    if (path === "/session/resume") { const err = new Error("forbidden"); err.status = 403; throw err; }
  } });
  await f.controller.initialize({ url: "https://app.test/app/" });
  const starts = f.calls.filter(c => c.path === "/session/start").length;
  await assert.rejects(f.controller.loadLesson(courses[0].lessons[0]));
  assert.equal(f.calls.filter(c => c.path === "/session/start").length, starts);
  assert.equal(f.controller.getView().error, "forbidden");
});

test("fresh launch enters catalog and removes its URL token without trusting cached lesson state", async t => {
  const f = fixture(t); let cleanUrl;
  await f.controller.initialize({ url: "https://app.test/app/?course_id=c&launch_token=obsolete&keep=1", replaceUrl: value => { cleanUrl = value; } });
  assert.equal(new URL(cleanUrl).searchParams.has("launch_token"), false);
  assert.equal(new URL(cleanUrl).searchParams.get("keep"), "1");
  assert.equal(f.controller.getView().screen, "lessons");
  assert.equal(f.calls.filter(c => c.path === "/session/resume").length, 0);
});

test("unavailable browser storage still permits authenticated entry and commands", async t => {
  const f = fixture(t);
  f.storage.getItem = f.storage.setItem = f.storage.removeItem = () => { throw new Error("disabled"); };
  await f.controller.initialize({ url: "https://app.test/app/?course_id=c" });
  await f.controller.loadLesson(courses[0].lessons[0]);
  await f.controller.dispatch({ type: "ask_question", text: "这个条件是什么意思？" });
  assert.equal(f.calls.at(-1).body.type, "ask_question");
});

test("browser locators are scoped to authenticated users and reset clears only one lesson", () => {
  const data = new Map([["student_last_course:u", "c"], ["student_browser_last_key:u", "u:c:L1"],
    ["student_browser_locator:u:c:L1", JSON.stringify({lessonId:"L1",phase:"done"})],
    ["student_browser_locator:u:c:L2", JSON.stringify({lessonId:"L2",phase:"done"})]]);
  const browser = createSessionBrowser(() => ({getItem:k=>data.get(k),setItem:(k,v)=>data.set(k,v),removeItem:k=>data.delete(k)}));
  assert.equal(browser.entry("https://app.test/app/", "u").lessonId, "L1");
  assert.equal(browser.entry("https://app.test/app/", "other").lessonId, null);
  assert.equal(browser.lessonPhase("u:c", "L1"), "done");
  browser.clear("u:c", "L1");
  assert.equal(browser.lessonPhase("u:c", "L1"), "");
  assert.equal(browser.lessonPhase("u:c", "L2"), "done");
});

test("the scheduled preparation poll uses one read and stops after the last subscriber leaves", async t => {
  const f = fixture(t, { state: { phase: "video", preparation: "pending" } }); await f.start();
  const before = f.calls.length;
  const [id, tick] = [...f.timers.entries()][0]; f.timers.delete(id); tick();
  await new Promise(setImmediate);
  assert.deepEqual(f.calls.slice(before).map(c => c.path), ["/session/s"]);
  assert.equal(f.timers.size, 1);
  f.unsubscribe(); assert.equal(f.timers.size, 0);
});

test("a confirmed lost acknowledgement clears the processing error without repeating the command", async t => {
  let sent = false;
  const f = fixture(t, { handler: ({ path, server, set }) => {
    if (path === "/session/s/commands" && !sent) {
      sent = true; set({ ...server, stateVersion: 7, messages: [{ role: "assistant", text: "已提交的提示" }] });
      throw new Error("acknowledgement lost");
    }
    if (path.endsWith("/status")) return { commandId: "cmd-1", status: "completed", sessionView: server };
  } }); await f.start();
  await assert.rejects(f.controller.dispatch({ type: "request_help", text: "提示" }));
  assert.equal(f.controller.getView().error, "acknowledgement lost");
  await f.controller.refresh();
  assert.equal(f.controller.getView().error, "");
  assert.equal(f.controller.getView().messages[0].text, "已提交的提示");
  assert.equal(f.calls.filter(c => c.path.endsWith("/commands")).length, 1);
});

test("content replacement exits replay and shows the new authoritative video", async t => {
  const f = fixture(t, { state: { phase: "done" } }); await f.start();
  await f.controller.dispatch({ type: "replay" });
  f.set({ phase: "video", contentGeneration: 1, stateVersion: 9, videoRevision: "new", messages: [], preparation: "pending" });
  await f.controller.refresh();
  assert.equal(f.controller.getView().screen, "video");
  assert.equal(f.controller.getView().contentGeneration, 1);
});

test("reset removes this lesson locator and returns the server catalog without deleting another lesson", async t => {
  const f = fixture(t, { state: { phase: "done", allowedCommands: ["reset_lesson"] }, handler: ({ path }) => {
    if (path === "/session/s/commands") return { commandId: "cmd-1", status: "completed", sessionView: {
      sessionId: "fresh", phase: "idle", courses, messages: [], stateVersion: 0, browserCourseKey: "u:c" } };
  } }); await f.start();
  f.stored.set("student_browser_locator:u:c:L1", "old");
  f.stored.set("student_browser_session:u:c:L1", "s");
  f.stored.set("student_browser_locator:u:c:L2", "another");
  await f.controller.dispatch({ type: "reset_lesson" });
  assert.equal(f.controller.getView().screen, "lessons");
  assert.equal(f.controller.getView().sessionId, "fresh");
  assert.equal(f.stored.has("student_browser_locator:u:c:L1"), false);
  assert.equal(f.stored.get("student_browser_locator:u:c:L2"), "another");
});

test("revocation during refresh returns to authenticated entry and stops polling", async t => {
  const f = fixture(t, { handler: ({ path }) => {
    if (path === "/session/s") { const error = new Error("session reset"); error.status = 410; throw error; }
  } }); await f.start();
  const starts = f.calls.filter(c => c.path === "/session/start").length;
  await f.controller.refresh();
  assert.equal(f.controller.getView().screen, "auth");
  assert.equal(f.timers.size, 0);
  assert.equal(f.calls.filter(c => c.path === "/session/start").length, starts);
});
