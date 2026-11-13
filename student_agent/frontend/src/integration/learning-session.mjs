/** Learning interaction Module: loadLesson / dispatch / subscribe.
 * SessionView owns teaching facts; screen only selects catalog, replay or postclass presentation.
 */
import { createLearningClient } from "./session-commands.mjs";
import { restoreStudentSession } from "./session-recovery.mjs";
import { createSessionBrowser } from "./session-browser.mjs";
import { requestSession } from "./session-http.mjs";

const routes = { start_discussion: "discussion", finish: "end", continue_after_class: "postclass/start",
  reset_lesson: "reset", retry_preparation: "prepare" };

export function createLearningSession({ request = requestSession, storage = () => globalThis.localStorage,
  setTimer = (fn, ms) => setTimeout(fn, ms), clearTimer = id => clearTimeout(id),
  pollMs = 5000, commandOptions = {} } = {}) {
  const browser = createSessionBrowser(storage);
  const client = createLearningClient({ request, storage, ...commandOptions });
  const listeners = new Set();
  let session = null, catalog = [], selected = null, screen = "loading", platformUrl = "";
  let courseId = "", userId = "", courseKey = "demo", demo = false, busy = false, error = "", connectionError = "";
  let errorVersion;
  let epoch = 0, abort = new AbortController(), timer, refreshInFlight;
  let stableLesson, stableLessonKey;
  let current = project();

  function project() {
    const courses = catalog.length ? catalog : session?.courses || [];
    const lessonId = selected?.id || session?.lessonId;
    const course = session?.courses?.find(c => c.lessons.some(l => l.id === lessonId))
      || courses.find(c => c.lessons.some(l => l.id === lessonId)) || courses[0] || null;
    let lesson = selected || course?.lessons.find(l => l.id === lessonId) || null;
    const lessonKey = JSON.stringify([lesson, session?.videoRevision]);
    if (lessonKey === stableLessonKey) lesson = stableLesson;
    else { stableLesson = lesson; stableLessonKey = lessonKey; }
    return { ...(session || {}), userId, screen, courses, course, lesson, platformUrl, busy, error, connectionError,
      messages: session?.messages || [], postclassMessages: session?.postclassMessages || [],
      flowVersion: session?.flowVersion || "legacy_recall_v3",
      preparation: session?.preparation || "idle", allowedCommands: session?.allowedCommands || [] };
  }
  function emit() { current = project(); for (const listener of listeners) listener(current); }
  function stopTimer() { if (timer !== undefined) clearTimer(timer); timer = undefined; }
  function cancel() { stopTimer(); abort.abort(); abort = new AbortController(); epoch++; refreshInFlight = null; }
  function ticket() { return { epoch, signal: abort.signal }; }
  function valid(t) { return t.epoch === epoch && !t.signal.aborted; }
  function schedule(delay = pollMs) {
    stopTimer();
    if (!listeners.size || !session?.lessonId || !["video", "discussion", "done", "postclass", "replay"].includes(screen)) return;
    const t = ticket();
    timer = setTimer(() => { timer = undefined; if (valid(t)) refresh().catch(() => {}); }, delay);
  }
  function adopt(incoming, t, { target, preserveScreen = false } = {}) {
    if (!valid(t) || !incoming?.sessionId) return;
    if (session?.sessionId === incoming.sessionId && session.stateVersion > incoming.stateVersion) return;
    const previous = session;
    session = incoming;
    if (error && incoming.stateVersion > errorVersion && !incoming.pendingSubmission) error = "";
    if (!(preserveScreen && screen === "replay" && previous?.lessonId === incoming.lessonId
          && previous?.contentGeneration === incoming.contentGeneration)) selected = null;
    if (!catalog.length || ["idle", "courses"].includes(incoming.phase)) catalog = incoming.courses || catalog;
    courseKey = incoming.browserCourseKey || courseKey;
    browser.save(incoming);
    const typedComplete = incoming.typedTeaching && incoming.postclassStage === "completed";
    if (target && (target !== "postclass" || incoming.phase === "postclass"
        || (incoming.phase === "done" && incoming.postclassStage && incoming.teachingStage !== "completed" && !typedComplete))) screen = target;
    else if (preserveScreen && previous?.lessonId === incoming.lessonId
        && previous?.contentGeneration === incoming.contentGeneration && previous?.phase === incoming.phase
        && !(screen === "postclass" && (incoming.teachingStage === "completed" || typedComplete))) {
      // A read refresh preserves replay/postclass presentation, never teaching state.
    } else screen = ["idle", "courses"].includes(incoming.phase) ? "lessons" : incoming.phase;
    connectionError = "";
    emit(); schedule();
  }
  const api = (t, path, method, body) => client.request(path, method, body, { signal: t.signal });

  async function operate(work, { navigate = false, target } = {}) {
    if (busy && !navigate) throw new Error("上一项操作仍在处理中");
    if (navigate) cancel();
    const t = ticket();
    busy = true; error = ""; stopTimer(); emit();
    try {
      const result = await work(t);
      if (!valid(t)) return current;
      if (result?.sessionId) adopt(result, t, { target });
      return current;
    } catch (failure) {
      if (!valid(t)) return current;
      if (failure.sessionView) adopt(failure.sessionView, t, { preserveScreen: true });
      if ([401, 403, 404].includes(failure.status)) { screen = "auth"; connectionError = ""; }
      error = failure.message; errorVersion = session?.stateVersion; emit();
      throw failure;
    } finally {
      if (valid(t)) { busy = false; emit(); schedule(); }
    }
  }

  async function initialize({ url, replaceUrl = () => {} }) {
    return operate(async t => {
      const clean = new URL(url);
      platformUrl = clean.origin;
      clean.searchParams.delete("launch_token");
      replaceUrl(clean.toString());
      const identity = await request("/session/identity", "GET", undefined, { signal: t.signal });
      if (!valid(t)) return;
      if (userId && identity.userId !== userId) { session = null; catalog = []; selected = null; }
      userId = identity.userId;
      client.setIdentity(userId);
      const entry = browser.entry(clean.toString(), userId);
      courseId = entry.courseId; courseKey = entry.courseKey;
      replaceUrl(entry.cleanUrl);
      const platform = await api(t, "/session/platform-entry").catch(failure => {
        if (t.signal.aborted) throw failure;
        return {};
      });
      if (!valid(t)) return;
      platformUrl = platform.platformUrl || ""; demo = Boolean(platform.demoEnabled);
      if (!courseId && !demo) { screen = "auth"; emit(); return; }
      const saved = await restoreStudentSession({
        api: (p, m, b) => api(t, p, m, b), courseId, lessonId: entry.lessonId,
        snapshot: entry.snapshot, sessionId: entry.sessionId, demo });
      if (!valid(t)) return;
      if (saved) return saved;
      if (!entry.fresh) browser.clear(courseKey, entry.lessonId, entry.key);
      return api(t, "/session/start", "POST", { course_id: courseId });
    }, { navigate: true }).catch(failure => { screen = "auth"; emit(); throw failure; });
  }

  async function loadLesson(lesson) {
    return operate(async t => {
      const locator = browser.locator(courseKey, lesson.id);
      const saved = await restoreStudentSession({ api: (p, m, b) => api(t, p, m, b),
        courseId, lessonId: lesson.id, snapshot: locator.snapshot, demo });
      if (!valid(t)) return;
      if (saved && saved.lessonId === lesson.id && saved.phase !== "idle") return saved;
      if (session?.lessonId) {
        const started = await api(t, "/session/start", "POST", { course_id: courseId });
        if (!valid(t)) return;
        adopt(started, t);
      }
      selected = lesson; screen = "lesson"; emit();
    }, { navigate: true });
  }

  async function refresh() {
    if (!session?.lessonId || busy) { schedule(); return current; }
    if (refreshInFlight?.epoch === epoch) return refreshInFlight.promise;
    const t = ticket(), sid = session.sessionId;
    const promise = (async () => {
      try { adopt(await api(t, `/session/${sid}`), t, { preserveScreen: true }); }
      catch (failure) {
        if (valid(t)) {
          connectionError = failure.message;
          if ([401, 403, 404, 410].includes(failure.status)) { screen = "auth"; error = failure.message; session = null; selected = null; catalog = []; }
          emit();
        }
      } finally { if (valid(t)) { refreshInFlight = null; schedule(); } }
      return current;
    })();
    refreshInFlight = { epoch, promise };
    return promise;
  }

  async function dispatch(action) {
    const type = action.type;
    if (type === "catalog" || type === "back_feedback") {
      cancel(); busy = false; error = ""; selected = null;
      screen = type === "catalog" ? "lessons" : "done";
      emit(); schedule(); return current;
    }
    const sid = session?.sessionId;
    if (!sid) throw new Error("请先进入课时");
    const dynamic = session.flowVersion === "dynamic_dialogue_v1";
    const technical = ["begin", "retry_preparation", "replay"];
    if (dynamic && !technical.includes(type) && !session.allowedCommands?.includes(type)) {
      throw new Error("当前学习状态不允许此操作，请刷新后重试");
    }
    let target;
    if (type === "continue_after_class") target = "postclass";
    if (type === "exit_after_class") target = "done";
    if (["postclass_answer", "request_help", "ask_question", "pause", "resume_activity"].includes(type)
        && screen === "postclass") target = "postclass";
    const exitScope = { lessonId: session.lessonId, generation: session.contentGeneration || 0 };
    return operate(async t => {
      if (type === "replay") {
        let playable = current.lesson;
        if (action.refresh || !playable?.playerUrl) {
          const result = await api(t, `/session/${sid}/playback`, "POST", {});
          if (result.courseId !== current.course?.id || result.lesson?.id !== session.lessonId
              || (current.lesson?.classroomId && result.lesson?.classroomId !== current.lesson.classroomId)) {
            throw new Error("播放信息与当前课时不匹配，请从平台重新进入课程");
          }
          playable = result.lesson;
        }
        if (!playable?.playerUrl) throw new Error("本课时暂时没有可播放的视频，请稍后重试或联系教师");
        if (valid(t)) { selected = playable; screen = "replay"; emit(); }
        return;
      }
      if (type === "begin") {
        const result = await api(t, `/session/${sid}/begin/${encodeURIComponent(current.lesson.id)}`, "POST");
        const playable = result.courses?.flatMap(c => c.lessons).find(l => l.id === current.lesson.id);
        if (!playable?.playerUrl) throw new Error("该课时没有可播放的视频");
        return result;
      }
      let result;
      if (type === "exit_after_class") {
        try { result = await api(t, `/session/${sid}/end`, "POST"); }
        catch (failure) {
          const latest = failure.sessionView;
          if (failure.code !== "VERSION_CONFLICT" || !valid(t) || !latest?.typedTeaching
              || latest.sessionId !== sid || latest.phase !== "done" || latest.lessonId !== exitScope.lessonId
              || (latest.contentGeneration || 0) !== exitScope.generation) throw failure;
          // The answer may have been accepted before its acknowledgement arrived.
          // Retry only this explicit exit against that same lesson's refreshed view.
          result = await api(t, `/session/${sid}/end`, "POST");
        }
      }
      else if (["submit_answer", "postclass_answer"].includes(type)) result = await api(t,
        `/session/${sid}/${type === "submit_answer" ? "message" : "postclass/message"}`, "POST", { text: action.text });
      else if (["request_help", "ask_question", "pause", "resume_activity"].includes(type)) result = await client.dispatch(
        sid, type, ["request_help", "ask_question"].includes(type) ? { text: action.text } : {}, { signal: t.signal });
      else if (routes[type]) result = await api(t, `/session/${sid}/${routes[type]}`, "POST",
        undefined);
      else throw new Error("未知的学习操作");
      if (valid(t) && type === "reset_lesson") browser.clear(courseKey, session.lessonId);
      return result;
    }, { target, navigate: type === "exit_after_class" });
  }

  return { initialize, loadLesson, dispatch, refresh, getView: () => current,
    lessonPhase: lessonId => browser.lessonPhase(courseKey, lessonId),
    subscribe(listener) {
      listeners.add(listener); listener(current); schedule();
      return () => { listeners.delete(listener); if (!listeners.size) cancel(); };
    } };
}
