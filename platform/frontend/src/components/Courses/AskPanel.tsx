import { useMutation, useQuery } from "@tanstack/react-query"
import { MessageCircleQuestion, Send } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { AgentSessionsService, type HistoryMessage } from "@/client"
import SessionBar from "@/components/AgentSessions/SessionBar"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useAgentSessions } from "@/hooks/useAgentSessions"
import useAuth from "@/hooks/useAuth"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

/** Local display state: server messages plus the in-flight streaming bubble. */
type Bubble = HistoryMessage & { streaming?: boolean }

/**
 * Chapter Q&A panel (student side), on the unified agent-session API.
 *
 * Multiple sessions per chapter: pick/switch in the session bar, start a new
 * one (old history stays), delete. History lives in the agent's checkpoint
 * store keyed by the session's thread; the server response is always the
 * source of truth. Sends go through the SSE stream (typewriter effect).
 */
const AskPanel = ({ chapterId }: { chapterId: string }) => {
  const [question, setQuestion] = useState("")
  const [history, setHistory] = useState<Bubble[]>([])
  const { showErrorToast } = useCustomToast()
  const abortRef = useRef<AbortController | null>(null)
  const { user } = useAuth()

  const {
    sessions,
    currentSession,
    listPending,
    createMutation,
    deleteMutation,
    renameMutation,
    selectSession,
    resetSelection,
    ensureSession,
    historyKey,
    sendMessageStream,
    afterTurn,
  } = useAgentSessions({
    agentKey: "chat",
    scopeType: "chapter",
    scopeId: chapterId,
  })

  const sessionId = currentSession?.id ?? null

  // Restore the persisted conversation for the session being shown.
  const { data: initialMessages } = useQuery({
    queryKey: historyKey(sessionId ?? "none"),
    enabled: !!user && !!sessionId,
    queryFn: () =>
      AgentSessionsService.readAgentSessionMessages({
        path: { session_id: sessionId! },
        query: {
          agent_key: "chat",
          scope_type: "chapter",
          scope_id: chapterId,
        },
      }),
  })

  // The display is bound to the session (§7.3, review finding #4): the
  // sessionId reference re-runs this effect on switch, so the previous
  // session's messages never linger during load or on failure; the fetched
  // history fills in once available.
  useEffect(() => {
    setHistory(sessionId ? (initialMessages?.data.messages ?? []) : [])
  }, [initialMessages, sessionId])

  // Abort the in-flight stream when the panel unmounts (chapter switch).
  useEffect(() => {
    return () => abortRef.current?.abort()
  }, [])

  const mutation = useMutation({
    mutationFn: async (q: string) => {
      const target = sessionId ?? (await ensureSession())
      if (!target) throw new Error("会话创建失败，请重试")
      const controller = new AbortController()
      abortRef.current = controller
      return sendMessageStream(target, q, {
        signal: controller.signal,
        onChunk: (text) =>
          setHistory((h) => {
            if (h[h.length - 1]?.role !== "assistant") return h
            const next = [...h]
            next[next.length - 1] = {
              ...next[next.length - 1],
              content: next[next.length - 1].content + text,
            }
            return next
          }),
      }).then(() => target)
    },
    // show the question + an empty reply bubble immediately; drop both if
    // the turn failed
    onMutate: (q) => {
      const snapshot = history
      setHistory((h) => [
        ...h,
        { role: "user", content: q },
        { role: "assistant", content: "", streaming: true },
      ])
      return { snapshot }
    },
    onSuccess: async (target) => {
      setQuestion("")
      // streaming text is display-only; re-sync from the checkpoint
      await afterTurn(target)
    },
    onError: (err, _q, ctx) => {
      if (err instanceof DOMException && err.name === "AbortError") return
      if (ctx?.snapshot) setHistory(ctx.snapshot)
      if (err.name === "SessionGoneError") {
        // the session row is gone — drop the stale selection, list refreshes
        resetSelection()
        showErrorToast("会话已失效，请重新选择后重发")
        return
      }
      handleError.call(showErrorToast, err)
    },
  })

  const onSubmit = () => {
    const q = question.trim()
    if (!q || mutation.isPending) return
    mutation.mutate(q)
  }

  return (
    <div className="mt-3 border-t pt-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h4 className="flex items-center gap-1.5 text-sm font-medium">
          <MessageCircleQuestion className="h-4 w-4 text-muted-foreground" />
          AI 问答
        </h4>
        <SessionBar
          sessions={sessions}
          currentId={sessionId}
          busy={listPending || mutation.isPending}
          onSelect={selectSession}
          onCreate={() => createMutation.mutate()}
          creating={createMutation.isPending}
          onRename={(id, title) => renameMutation.mutate({ id, title })}
          renaming={renameMutation.isPending}
          onDelete={(id) => deleteMutation.mutate(id)}
          deleting={deleteMutation.isPending}
        />
      </div>
      {history.length > 0 && (
        <div className="flex flex-col gap-3 mb-3 max-h-80 overflow-y-auto">
          {history.map((m, i) => (
            <div key={i} className="flex flex-col gap-1">
              {m.role === "user" ? (
                <p className="self-end rounded-lg bg-primary px-3 py-1.5 text-sm text-primary-foreground max-w-[85%]">
                  {m.content}
                </p>
              ) : (
                <p className="self-start rounded-lg bg-muted px-3 py-1.5 text-sm whitespace-pre-wrap max-w-[85%]">
                  {m.content || (m.streaming ? "思考中…" : "")}
                </p>
              )}
            </div>
          ))}
        </div>
      )}
      <div className="flex gap-2">
        <Input
          placeholder="针对本章节内容提问…"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") onSubmit()
          }}
          disabled={mutation.isPending || createMutation.isPending}
        />
        <Button
          size="icon"
          onClick={onSubmit}
          disabled={
            mutation.isPending || createMutation.isPending || !question.trim()
          }
        >
          <Send className="h-4 w-4" />
        </Button>
      </div>
    </div>
  )
}

export default AskPanel
