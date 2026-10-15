/** Refresh, network failure and a new tab do not mean the lesson is finished. */
export function shouldRenewSession(state) {
  return !state || state.status === "ended";
}

export function studentStorageScope() {
  try {
    const platform = JSON.parse(sessionStorage.getItem("__studentPlatform") || "null");
    if (platform && platform.userId) return "platform:" + platform.userId + ":" + platform.courseId;
    const student = JSON.parse(localStorage.getItem("ai-learn.student") || "null");
    if (student && student.studentId) return "student:" + student.studentId;
  } catch (error) {}
  return "local";
}

/** Opaque device key: scope playback to the signed-in learner without putting
 * their account id in iframe URLs. This key grants no access. */
export function playbackStorageKey() {
  const key = "ai-learn.playback-scope." + studentStorageScope();
  try {
    const saved = localStorage.getItem(key);
    if (saved && /^[a-zA-Z0-9-]{16,80}$/.test(saved)) return saved;
    const value = crypto.randomUUID();
    localStorage.setItem(key, value);
    return value;
  } catch (error) {
    return crypto.randomUUID();
  }
}
