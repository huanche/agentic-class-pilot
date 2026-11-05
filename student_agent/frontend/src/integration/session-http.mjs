/** Transport Adapter shared by loading, command recovery, playback and polling. */
let csrfToken = "";
export async function requestSession(path, method = "GET", body, { signal } = {}) {
  const response = await fetch(`/api${path}`, { method, signal, credentials: "same-origin",
    headers: { ...(body ? { "Content-Type": "application/json" } : {}),
      ...(method !== "GET" && csrfToken ? { "X-CSRF-Token": csrfToken } : {}) },
    body: body ? JSON.stringify(body) : undefined });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof data.detail === "object" ? data.detail : data;
    const error = new Error(detail?.detail || data.failure?.detail || `请求失败 (${response.status})`);
    error.status = response.status;
    error.code = detail?.code;
    if (data.commandId) error.commandResult = data;
    throw error;
  }
  if (path === "/session/identity") csrfToken = data.csrfToken || "";
  return data;
}
