/** The host supplies an opaque, per-account device key. It is storage scope,
 * never authentication; classroom access still requires the platform cookie. */
export function studentPlaybackStorageId(stageId: string, search: string): string {
  const key = new URLSearchParams(search).get('resumeKey');
  return key && /^[a-zA-Z0-9-]{16,80}$/.test(key) ? `student:${key}:${stageId}` : stageId;
}
