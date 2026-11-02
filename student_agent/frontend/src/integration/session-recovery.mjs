/** Browser records locate a lesson; only the authenticated server restores it. */
export async function restoreStudentSession({ api, launchToken, lessonId, snapshot, sessionId, demo = false }) {
  if (launchToken) {
    if (!lessonId || lessonId === "catalog") return null;
    try {
      return await api("/session/resume", "POST", { launch_token: launchToken, lesson_id: lessonId });
    } catch (error) {
      if (error.status === 404) return null;
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
