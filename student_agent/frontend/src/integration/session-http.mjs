/** Transport Adapter shared by loading, command recovery, playback and polling. */
export async function requestSession(path, method = "GET", body, { signal } = {}) {
  const response = await fetch(`/api${path}`, { method, signal,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.detail || data.failure?.detail || `请求失败 (${response.status})`);
    error.status = response.status;
    error.code = data.code;
    if (data.commandId) error.commandResult = data;
    throw error;
  }
  return data;
}
