/** Browser records locate a lesson; only the authenticated server restores it. */
export async function restoreStudentSession({ api, courseId, lessonId, snapshot, sessionId, demo = false }) {
  if (courseId) {
    if (!lessonId || lessonId === "catalog") return null;
    try {
      return await api("/session/resume", "POST", { course_id: courseId, lesson_id: lessonId });
    } catch (error) {
      if (error.status === 404 && error.code === "HISTORY_NOT_FOUND") return null;
      // A revoked/expired identity or an unavailable database is not empty history.
      throw error;
    }
  }
  if (!demo) return null;
  try {
    if (snapshot) return await api("/session/browser-restore", "POST", { snapshot });
    if (sessionId) return await api(`/session/${sessionId}`);
    return null;
  } catch (error) {
    if (error.status === 400 || error.status === 404) return null;
    throw error;
  }
}
