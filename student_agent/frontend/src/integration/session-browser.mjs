/** Browser data locates a lesson and carries retry identity; it never restores formal teaching state. */
export function createSessionBrowser(storage = () => globalThis.localStorage) {
  const get = key => { try { return storage()?.getItem(key); } catch { return null; } };
  const set = (key, value) => { try { storage()?.setItem(key, value); } catch {} };
  const remove = key => { try { storage()?.removeItem(key); } catch {} };
  function snapshot(value) {
    try {
      const raw = value.split(".")[0].replace(/-/g, "+").replace(/_/g, "/");
      return JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(raw.padEnd(Math.ceil(raw.length / 4) * 4, "=")), c => c.charCodeAt(0))));
    } catch { return null; }
  }
  function courseFromToken(token) {
    const value = snapshot(token);
    return value?.uid && value?.cid ? `${value.uid}:${value.cid}` : "";
  }
  function entry(url) {
    const parsed = new URL(url);
    const fresh = parsed.searchParams.get("launch_token");
    const courseKey = (fresh && courseFromToken(fresh)) || get("student_browser_last_course_key") || "demo";
    const token = fresh || get(`student_browser_token:${courseKey}`) || "";
    if (token) set(`student_browser_token:${courseKey}`, token);
    const legacyKey = `student_browser_snapshot:${courseKey}`;
    const legacy = get(legacyKey);
    const lessonId = snapshot(legacy)?.lessonId;
    if (lessonId) {
      const key = `${courseKey}:${lessonId}`;
      if (!get(`student_browser_snapshot:${key}`)) set(`student_browser_snapshot:${key}`, legacy);
      remove(legacyKey);
      remove(`student_browser_session:${courseKey}`);
      set("student_browser_last_key", key);
    }
    parsed.searchParams.delete("launch_token");
    const key = fresh ? `${courseKey}:catalog` : get("student_browser_last_key") || `${courseKey}:catalog`;
    return { token, courseKey, fresh: Boolean(fresh), cleanUrl: parsed.toString(), ...locator(courseKey, null, key) };
  }
  function locator(courseKey, lessonId, key = `${courseKey}:${lessonId}`) {
    const value = get(`student_browser_snapshot:${key}`);
    return { key, snapshot: value, sessionId: get(`student_browser_session:${key}`),
      lessonId: lessonId || snapshot(value)?.lessonId || (key.startsWith(`${courseKey}:`) ? key.slice(courseKey.length + 1) : null) };
  }
  function save(view) {
    if (!view?.browserKey || !view.browserSnapshot) return;
    set(`student_browser_snapshot:${view.browserKey}`, view.browserSnapshot);
    set(`student_browser_session:${view.browserKey}`, view.sessionId);
    set("student_browser_last_key", view.browserKey);
    if (view.browserCourseKey) set("student_browser_last_course_key", view.browserCourseKey);
  }
  function clear(courseKey, lessonId, key = `${courseKey}:${lessonId}`) {
    remove(`student_browser_snapshot:${key}`);
    remove(`student_browser_session:${key}`);
    if (snapshot(get(`student_browser_snapshot:${courseKey}`))?.lessonId === lessonId) {
      remove(`student_browser_snapshot:${courseKey}`);
      remove(`student_browser_session:${courseKey}`);
    }
  }
  return { entry, locator, save, clear,
    lessonPhase: (courseKey, lessonId) => snapshot(get(`student_browser_snapshot:${courseKey}:${lessonId}`))?.phase || "" };
}
