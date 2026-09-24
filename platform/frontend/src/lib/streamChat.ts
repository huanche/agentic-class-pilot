export interface StreamFrame {
  content: string
  done: boolean
}

interface StreamChatOptions {
  /** Called for every non-final frame with that chunk's text. */
  onChunk: (text: string) => void
  /** Abort mid-stream (component unmount, user cancel). */
  signal?: AbortSignal
  /** Full endpoint path of the stream route (the legacy chat default was
   *  removed together with that route — callers pass the unified
   *  /agent-sessions stream path). */
  endpoint: string
  /** Extra fields merged into the request body (e.g. outline's course_id). */
  extraBody?: Record<string, unknown>
}

/**
 * POST a chat message and consume the SSE reply stream.
 *
 * Deliberately native fetch instead of the generated axios client: browser
 * axios rides on XHR, which cannot read a response body incrementally — and
 * incremental reading is the entire point. Frame protocol (see the
 * agent-sessions routes): one `data: {"content", "done"}` JSON event per
 * chunk; the stream ALWAYS ends with a done=true frame — empty content on
 * success, a readable error message on failure.
 */
export async function streamChat(
  _sessionId: string,
  message: string,
  { onChunk, signal, endpoint, extraBody }: StreamChatOptions,
): Promise<void> {
  const response = await fetch(endpoint, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      messages: [{ role: "user", content: message }],
      ...extraBody,
    }),
    signal,
    credentials: "include",
  })

  if (response.status === 404) {
    // The session row is gone (account switch without reload, deleted
    // session) — a distinct error name so the caller can rebuild the
    // session instead of just showing a dead panel.
    const err = new Error("会话已失效")
    err.name = "SessionGoneError"
    throw err
  }

  if (!response.ok || !response.body) {
    // Failure before the stream opened (401/422…): FastAPI sends JSON.
    let detail = `请求失败（HTTP ${response.status}）`
    try {
      const data = (await response.json()) as { detail?: unknown }
      if (data?.detail) detail = String(data.detail)
    } catch {
      /* non-JSON body — keep the default message */
    }
    throw new Error(detail)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  let completed = false

  const handleFrame = (frame: StreamFrame): "continue" | "done" | "error" => {
    if (frame.done) {
      if (frame.content) return "error" // error frame: done + message
      return "done"
    }
    if (frame.content) onChunk(frame.content)
    return "continue"
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    let sep = buffer.indexOf("\n\n")
    while (sep !== -1) {
      const rawEvent = buffer.slice(0, sep)
      buffer = buffer.slice(sep + 2)

      const line = rawEvent.split("\n").find((l) => l.startsWith("data: "))
      if (line) {
        const frame = JSON.parse(line.slice("data: ".length)) as StreamFrame
        const outcome = handleFrame(frame)
        if (outcome === "done") {
          completed = true
          return
        }
        if (outcome === "error") {
          completed = true
          throw new Error(frame.content)
        }
      }
      sep = buffer.indexOf("\n\n")
    }
  }

  if (!completed) {
    // Server closed the connection without a done=true frame.
    throw new Error("连接中断，请重试")
  }
}
