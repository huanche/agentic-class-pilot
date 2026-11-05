/** Cookie stays HttpOnly; this value protects browser writes and grants no identity. */
export async function learningCsrfHeaders(): Promise<Record<string, string>> {
  const response = await fetch("/api/v1/login/session", { credentials: "same-origin", cache: "no-store" })
  const data = await response.json()
  if (!response.ok) throw new Error(data.detail || "请重新登录平台")
  return { "X-CSRF-Token": data.csrfToken }
}
