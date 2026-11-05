/** User-scoped locators; browser data is never identity or authoritative progress. */
export function createSessionBrowser(storage = () => globalThis.localStorage) {
  const get = key => { try { return storage()?.getItem(key); } catch { return null; } };
  const set = (key, value) => { try { storage()?.setItem(key, value); } catch {} };
  const remove = key => { try { storage()?.removeItem(key); } catch {} };
  function read(key) { try { return JSON.parse(get(`student_browser_locator:${key}`)); } catch { return null; } }
  function entry(url, userId) {
    const parsed = new URL(url);
    parsed.searchParams.delete("launch_token");
    try {
      const keys = [];
      for (let i = 0; i < storage().length; i++) {
        const key = storage().key(i);
        if (key?.startsWith("student_browser_token:")) keys.push(key);
      }
      keys.forEach(remove);
    } catch {}
    const fresh = Boolean(parsed.searchParams.get("course_id"));
    const courseId = parsed.searchParams.get("course_id") || get(`student_last_course:${userId}`) || "";
    const courseKey = `${userId}:${courseId}`;
    const previous = get(`student_browser_last_key:${userId}`);
    const key = previous?.startsWith(`${courseKey}:`) ? previous : `${courseKey}:catalog`;
    return { courseId, courseKey, fresh, cleanUrl: parsed.toString(), ...locator(courseKey, null, key) };
  }
  function locator(courseKey, lessonId, key = `${courseKey}:${lessonId}`) {
    const value = read(key);
    return { key, sessionId: value?.sessionId, lessonId: lessonId || value?.lessonId || null };
  }
  function save(view) {
    if (!view?.browserKey || !view.userId) return;
    set(`student_browser_locator:${view.browserKey}`, JSON.stringify({
      sessionId: view.sessionId, lessonId: view.lessonId, phase: view.phase }));
    set(`student_browser_last_key:${view.userId}`, view.browserKey);
    const courseId = view.courses?.[0]?.id;
    if (courseId) set(`student_last_course:${view.userId}`, courseId);
  }
  function clear(courseKey, lessonId, key = `${courseKey}:${lessonId}`) {
    remove(`student_browser_locator:${key}`);
    remove(`student_browser_snapshot:${key}`);
    remove(`student_browser_session:${key}`);
  }
  return { entry, locator, save, clear,
    lessonPhase: (courseKey, lessonId) => read(`${courseKey}:${lessonId}`)?.phase || "" };
}
