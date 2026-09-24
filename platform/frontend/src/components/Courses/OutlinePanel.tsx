import { useMutation, useQuery } from "@tanstack/react-query"
import { ClipboardList, Send } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { AgentSessionsService, type HistoryMessage } from "@/client"
import SessionBar from "@/components/AgentSessions/SessionBar"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { useAgentSessions } from "@/hooks/useAgentSessions"
import useAuth from "@/hooks/useAuth"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

/** Local display state: server messages plus the in-flight streaming bubble. */
type Bubble = HistoryMessage & { streaming?: boolean }

/**
 * Legacy import (docs/agent-isolation-plan.md §8.2): report every
 * `outline-thread:{userId}:{courseId}` pair still living in localStorage to
 * the backend, which verifies and binds what it can.
 *
 * Deliberately re-reported on every mount with NO "already reported" marker
 * (the backend dedups by thread_id; a client-side marker proved fragile — a
 * failed report would orphan history forever). Duplicates are NOT deduped
 * client-side either: the same uuid under two courses must reach the backend
 * so its ambiguity check can classify the thread as 待归类 (review finding #5).
 */
const importLegacyThreads = async (userId: string) => {
  const hints: { course_id: string; thread_uuid: string }[] = []
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i)
    if (!key) continue
    const match = key.match(/^outline-thread:([^:]+):(.+)$/)
    if (!match || match[1] !== userId) continue
    const threadUuid = localStorage.getItem(key)
    if (!threadUuid) continue
    hints.push({ course_id: match[2], thread_uuid: threadUuid })
  }
  if (hints.length === 0) return
  await AgentSessionsService.importOutlineHints({ body: { hints } })
}

/**
 * Teaching-outline panel (teacher side), on the unified agent-session API.
 *
 * Sessions are server-side rows now (scope = the course), so history follows
 * the teacher across devices. Multiple outlines per course: switch in the
 * session bar, start a new one (the old outline stays in the list), delete.
 */
const OutlinePanel = ({ courseId }: { courseId: string }) => {
  const [revision, setRevision] = useState("")
  const [history, setHistory] = useState<Bubble[]>([])
  const [hintsReady, setHintsReady] = useState(false)
  const { showErrorToast } = useCustomToast()
  const abortRef = useRef<AbortController | null>(null)
  const { user } = useAuth()

  // Legacy import runs once per user before the session list loads.
  useEffect(() => {
    if (!user) return
    importLegacyThreads(user.id).finally(() => setHintsReady(true))
  }, [user])

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
    agentKey: "outline",
    scopeType: "course",
    scopeId: courseId,
    enabled: hintsReady,
  })

  const sessionId = currentSession?.id ?? null

  const { data: initialMessages } = useQuery({
    queryKey: historyKey(sessionId ?? "none"),
    enabled: !!user && !!sessionId,
    queryFn: () =>
      AgentSessionsService.readAgentSessionMessages({
        path: { session_id: sessionId! },
        query: {
          agent_key: "outline",
          scope_type: "course",
          scope_id: courseId,
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

  // Abort the in-flight stream when the panel unmounts (course switch).
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
      setRevision("")
      await afterTurn(target)
    },
    onError: (err, _q, ctx) => {
      if (err instanceof DOMException && err.name === "AbortError") return
      if (ctx?.snapshot) setHistory(ctx.snapshot)
      if (err.name === "SessionGoneError") {
        resetSelection()
        showErrorToast("会话已失效，请重新选择后重试")
        return
      }
      handleError.call(showErrorToast, err)
    },
  })

  const onSubmit = () => {
    const q = revision.trim()
    if (!q || mutation.isPending) return
    mutation.mutate(q)
  }

  return (
    <Card className="mt-6">
      <CardHeader>
        <CardTitle className="flex items-center justify-between gap-2 text-lg">
          <span className="flex items-center gap-2">
            <ClipboardList className="h-5 w-5 text-muted-foreground" />
            教学大纲助手
          </span>
          <SessionBar
            sessions={sessions}
            currentId={sessionId}
            busy={listPending || mutation.isPending}
            onSelect={selectSession}
            onCreate={() => {
              createMutation.mutate()
              setHistory([]) // fresh session → fresh outline area
            }}
            creating={createMutation.isPending}
            onRename={(id, title) => renameMutation.mutate({ id, title })}
            renaming={renameMutation.isPending}
            onDelete={(id) => {
              deleteMutation.mutate(id)
              setHistory([])
            }}
            deleting={deleteMutation.isPending}
          />
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {history.length === 0 && (
          <p className="text-sm text-muted-foreground">
            直接说"生成本课程的教学大纲"，或先描述课程目标与课时安排；助手会结合课程章节生成，并支持多轮修订。
          </p>
        )}
        {history.length > 0 && (
          <div className="flex max-h-96 flex-col gap-2 overflow-y-auto">
            {history.map((m, i) => (
              <div key={i} className="flex flex-col gap-1">
                {m.role === "user" ? (
                  <p className="max-w-[85%] self-end rounded-lg bg-primary px-3 py-1.5 text-sm text-primary-foreground">
                    {m.content}
                  </p>
                ) : (
                  <p className="max-w-[85%] self-start rounded-lg bg-muted px-3 py-1.5 text-sm whitespace-pre-wrap">
                    {m.content || (m.streaming ? "思考中…" : "")}
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
        <div className="flex gap-2">
          <Input
            placeholder="例如：生成 48 学时的教学大纲 / 把第一单元拆成两个…"
            value={revision}
            onChange={(e) => setRevision(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") onSubmit()
            }}
            disabled={mutation.isPending || createMutation.isPending}
          />
          <Button
            size="icon"
            onClick={onSubmit}
            disabled={
              mutation.isPending || createMutation.isPending || !revision.trim()
            }
          >
            <Send className="h-4 w-4" />
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

export default OutlinePanel
