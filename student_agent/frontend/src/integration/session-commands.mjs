/** Preserve a submission's identity across HTTP failures, reloads and server recovery. */
export function createLearningClient({ request, storage = () => globalThis.localStorage,
  createId = () => globalThis.crypto.randomUUID(), wait = (ms, signal) => new Promise((resolve, reject) => {
    const cancel = () => { clearTimeout(timer); reject(signal.reason); };
    const timer = setTimeout(() => { signal?.removeEventListener("abort", cancel); resolve(); }, ms);
    signal?.addEventListener("abort", cancel, { once: true });
    if (signal?.aborted) cancel();
  }),
  pollLimit = 120 } = {}) {
  const views = new Map();
  let userId = "";
  const pending = new Map();
  const inFlight = new Map();
  const key = sid => `student_pending_command:${userId}:${sid}`;
  function read(sid) {
    if (pending.has(sid)) return pending.get(sid);
    try { return JSON.parse(storage().getItem(key(sid))); } catch { return null; }
  }
  function save(sid, command) {
    pending.set(sid, command);
    try {
      if (command) storage().setItem(key(sid), JSON.stringify(command));
      else storage().removeItem(key(sid));
    } catch { /* In-memory retry still works if browser storage is unavailable. */ }
  }
  function observe(view) {
    if (!view?.sessionId) return view;
    const sid = view.sessionId;
    const previous = views.get(sid);
    if (view.userId && userId && view.userId !== userId) throw new Error("学习账号已变化，请刷新页面");
    if (!userId && view.userId) userId = view.userId;
    // Migrate a legacy pending submission only after this view was authorized by the server.
    if (userId && !read(sid)) {
      try {
        const legacy = storage().getItem(`student_pending_command:${sid}`);
        if (legacy) { save(sid, JSON.parse(legacy)); storage().removeItem(`student_pending_command:${sid}`); }
      } catch {}
    }
    if (previous && previous.stateVersion > view.stateVersion) return previous;
    views.set(sid, view);
    const submission = view.pendingSubmission;
    if (submission && read(sid)?.commandId !== submission.commandId) {
      const { commandId, type, payload, expectedStateVersion, contentGeneration } = submission;
      save(sid, { commandId, type, payload, expectedStateVersion, contentGeneration });
    }
    return view;
  }
  async function submit(sid, command, options = {}) {
    const key = `${sid}:${command.commandId}`;
    if (inFlight.has(key)) return inFlight.get(key);
    const running = perform(sid, command, options);
    inFlight.set(key, running);
    try { return await running; } finally { if (inFlight.get(key) === running) inFlight.delete(key); }
  }
  async function perform(sid, command, options) {
    const check = () => options.signal?.throwIfAborted();
    check();
    let receipt;
    try {
      receipt = await request(`/session/${sid}/commands`, "POST", { ...command }, options);
    } catch (error) {
      if (!error.commandResult) {
        if (["VERSION_CONFLICT", "CONTENT_CHANGED", "TASK_CHANGED", "COMMAND_CANCELLED", "SESSION_RESET"].includes(error.code)) {
          save(sid, null);
          // Refresh the authoritative task; never replay the old answer against a new task.
          const latest = await request(`/session/${sid}`, "GET", undefined, options).catch(() => null);
          if (latest) error.sessionView = observe(latest);
        }
        throw error;
      }
      receipt = error.commandResult;
    }
    check();
    for (let attempt = 0; ["pending", "processing"].includes(receipt.status) && attempt < pollLimit; attempt++) {
      if (receipt.sessionView) observe(receipt.sessionView);
      await wait(500, options.signal);
      check();
      receipt = await request(`/session/${sid}/commands/${command.commandId}/status`, "POST", {}, options);
    }
    check();
    const view = observe(receipt.sessionView);
    if (receipt.status === "completed") {
      if (read(sid)?.commandId === command.commandId) save(sid, null);
      return view;
    }
    if (receipt.status === "cancelled" && read(sid)?.commandId === command.commandId) save(sid, null);
    const cancelled = receipt.status === "cancelled";
    const error = new Error(receipt.failure?.detail || (cancelled
      ? "该提交已取消，请刷新学习状态" : "回答仍在处理中，请稍后重试"));
    error.code = receipt.failure?.code || (cancelled ? "COMMAND_CANCELLED" : "COMMAND_PROCESSING");
    error.sessionView = view;
    throw error;
  }
  const kinds = { discussion: "start_discussion", message: "submit_answer", end: "finish",
    "postclass/start": "continue_after_class", "postclass/message": "postclass_answer", reset: "reset_lesson" };
  function makeCommand(sid, kind, payload) {
    const view = views.get(sid);
    if (Object.hasOwn(payload, "text") && view.currentTaskPublic?.taskId) payload.taskId = view.currentTaskPublic.taskId;
    const existing = read(sid);
    const samePayload = JSON.stringify(existing?.payload) === JSON.stringify(payload)
      || (["submit_answer", "postclass_answer"].includes(kind) && Object.hasOwn(payload, "text")
          && existing?.payload?.text === payload.text && !existing.payload.taskId);
    const command = existing?.type === kind && samePayload ? existing
      : { commandId: createId(), expectedStateVersion: view.stateVersion,
          contentGeneration: view.contentGeneration || 0, type: kind, payload };
    save(sid, command);
    return command;
  }
  return {
    setIdentity(id) {
      if (id !== userId) { views.clear(); pending.clear(); inFlight.clear(); }
      userId = id || "";
    },
    async dispatch(sid, type, payload = {}, options = {}) {
      const view = views.get(sid);
      if (!userId || !Number.isSafeInteger(view?.stateVersion)) throw new Error("此操作需要正式学习会话");
      return submit(sid, makeCommand(sid, type, { ...payload }), options);
    },
    async request(path, method = "GET", body, options = {}) {
      const match = path.match(/^\/session\/([^/]+)(?:\/(.*))?$/);
      const sid = match?.[1];
      const kind = method === "POST" && kinds[match?.[2]];
      const view = views.get(sid);
      if (kind && userId && Number.isSafeInteger(view?.stateVersion)) {
        const payload = kind === "submit_answer" || kind === "postclass_answer" ? { text: body.text } : {};
        return submit(sid, makeCommand(sid, kind, payload), options);
      }
      const incoming = await request(path, method, body, options);
      options.signal?.throwIfAborted();
      const loaded = observe(incoming);
      const submission = loaded?.pendingSubmission;
      if (submission && ["pending", "processing"].includes(submission.status) && userId) {
        try { return await submit(loaded.sessionId, read(loaded.sessionId), options); }
        catch (error) { if ([401, 403].includes(error.status)) throw error; return error.sessionView || loaded; }
      }
      const saved = loaded?.sessionId && read(loaded.sessionId);
      if (saved && !submission && userId) {
        // An acknowledgement may have been lost even though the server already finished.
        try {
          const receipt = await request(`/session/${loaded.sessionId}/commands/${saved.commandId}/status`,
            "POST", {}, options);
          options.signal?.throwIfAborted();
          if (["completed", "cancelled"].includes(receipt.status)
              && read(loaded.sessionId)?.commandId === saved.commandId) save(loaded.sessionId, null);
          return observe(receipt.sessionView || loaded);
        } catch (error) { if ([401, 403].includes(error.status)) throw error; /* Keep the saved submission until confirmed. */ }
      }
      return loaded;
    },
  };
}
