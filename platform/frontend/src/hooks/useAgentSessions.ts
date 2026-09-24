import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { isAxiosError } from "axios"
import { useCallback, useMemo, useRef, useState } from "react"

import { type AgentSessionPublic, AgentSessionsService } from "@/client"
import useAuth from "@/hooks/useAuth"
import useCustomToast from "@/hooks/useCustomToast"
import { streamChat } from "@/lib/streamChat"
import { handleError } from "@/utils"

interface UseAgentSessionsArgs {
  agentKey: string
  scopeType: string
  scopeId: string
  /** Gate the queries (e.g. until the outline import hints have run). */
  enabled?: boolean
}

const isNotFound = (err: unknown): boolean =>
  isAxiosError(err) && err.response?.status === 404

/**
 * Shared multi-session management for every agent panel
 * (docs/agent-isolation-plan.md §4.3/§7.4).
 *
 * Selection model (review findings #2/#7): the *chosen* id is authoritative
 * the moment the user picks or creates a session — it must NOT wait for the
 * list refetch (a fresh id absent from the stale list would otherwise fall
 * back to the previous session). The stored preference is validated
 * server-side through POST /resolve, so a session beyond the list's first
 * page still resolves correctly and "not loaded" is never mistaken for
 * "does not exist". The list only feeds the dropdown.
 */
export const useAgentSessions = ({
  agentKey,
  scopeType,
  scopeId,
  enabled = true,
}: UseAgentSessionsArgs) => {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const userId = user?.id ?? "anon"

  const listKey = useMemo(
    () => ["agent-sessions", userId, agentKey, scopeType, scopeId],
    [agentKey, scopeId, scopeType, userId],
  )
  const resolveKey = useMemo(
    () => ["agent-session-resolve", userId, agentKey, scopeType, scopeId],
    [agentKey, scopeId, scopeType, userId],
  )
  // §7.4 — the local choice remembers which session was last selected; the
  // backend session list stays the source of truth for ownership.
  const prefStorageKey = `agent-session-pref:${userId}:${agentKey}:${scopeType}:${scopeId}`

  // explicit choice for this visit: set instantly, never gated on queries
  const [chosenId, setChosenId] = useState<string | null>(null)

  const listQuery = useQuery({
    queryKey: listKey,
    enabled: !!user && enabled && !!scopeId,
    queryFn: () =>
      AgentSessionsService.listAgentSessions({
        query: {
          agent_key: agentKey,
          scope_type: scopeType,
          scope_id: scopeId,
        },
      }),
  })
  const sessions: AgentSessionPublic[] = listQuery.data?.data.data ?? []

  // server-side pick: stored preference (exact match, 404 if stale → drop it
  // and retry without) or the most recently active session; null = scope empty
  const resolveQuery = useQuery({
    queryKey: resolveKey,
    enabled: !!user && enabled && !!scopeId,
    staleTime: 60_000,
    queryFn: async (): Promise<AgentSessionPublic | null> => {
      const body = {
        agent_key: agentKey,
        scope: { type: scopeType, id: scopeId },
      }
      const preferred = localStorage.getItem(prefStorageKey)
      if (preferred) {
        try {
          const res = await AgentSessionsService.resolveAgentSession({
            body: { ...body, preferred_session_id: preferred },
          })
          return res.data
        } catch (err) {
          if (!isNotFound(err)) throw err
          localStorage.removeItem(prefStorageKey) // stale pref: drop, refall
        }
      }
      return (await AgentSessionsService.resolveAgentSession({ body })).data
    },
  })

  const currentSession: AgentSessionPublic | null = useMemo(() => {
    if (chosenId) {
      // chosen wins even before the list refetch lands; a stub stands in
      // until the row arrives (title falls back to "新会话" in the UI)
      return (
        sessions.find((s) => s.id === chosenId) ?? {
          id: chosenId,
          agent_key: agentKey,
          scope_type: scopeType,
          scope_id: scopeId,
          title: "",
          status: "active",
        }
      )
    }
    return resolveQuery.data ?? null
  }, [agentKey, chosenId, resolveQuery.data, scopeId, scopeType, sessions])

  const selectSession = useCallback(
    (id: string) => {
      setChosenId(id)
      localStorage.setItem(prefStorageKey, id)
    },
    [prefStorageKey],
  )

  const resetSelection = useCallback(() => {
    localStorage.removeItem(prefStorageKey)
    setChosenId(null)
    queryClient.invalidateQueries({ queryKey: listKey })
    queryClient.invalidateQueries({ queryKey: resolveKey })
  }, [listKey, prefStorageKey, queryClient, resolveKey])

  // §7.1 — one idempotency key per new-session intent: network retries
  // return the same session; the key is dropped only after a confirmed create
  const createKeyRef = useRef<string | null>(null)
  const createMutation = useMutation({
    mutationFn: () => {
      createKeyRef.current ??= crypto.randomUUID()
      return AgentSessionsService.createAgentSession({
        body: {
          agent_key: agentKey,
          scope: { type: scopeType, id: scopeId },
          idempotency_key: createKeyRef.current,
        },
      })
    },
    onSuccess: (res) => {
      createKeyRef.current = null
      // chosen immediately — a send right after must land in the NEW session
      // even while the list refetch is still in flight
      selectSession(res.data.id)
      queryClient.invalidateQueries({ queryKey: listKey })
      queryClient.invalidateQueries({ queryKey: resolveKey })
    },
    onError: handleError.bind(showErrorToast),
  })

  /** The session to send into — creating one first when the scope is empty
   * (§4.1 "首次发送"). Returns null while creation is in flight/failed. */
  const ensureSession = useCallback(async (): Promise<string | null> => {
    if (currentSession) return currentSession.id
    try {
      const res = await createMutation.mutateAsync()
      return res.data.id
    } catch {
      return null
    }
  }, [createMutation, currentSession])

  const deleteMutation = useMutation({
    mutationFn: (id: string) =>
      AgentSessionsService.deleteAgentSession({
        path: { session_id: id },
        query: {
          agent_key: agentKey,
          scope_type: scopeType,
          scope_id: scopeId,
        },
      }),
    onSuccess: async (_res, id) => {
      if (localStorage.getItem(prefStorageKey) === id) {
        localStorage.removeItem(prefStorageKey)
      }
      setChosenId(null)
      showSuccessToast("会话已删除")
      await queryClient.invalidateQueries({ queryKey: listKey })
      await queryClient.invalidateQueries({ queryKey: resolveKey })
    },
    onError: handleError.bind(showErrorToast),
  })

  const renameMutation = useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) =>
      AgentSessionsService.updateAgentSession({
        path: { session_id: id },
        query: {
          agent_key: agentKey,
          scope_type: scopeType,
          scope_id: scopeId,
        },
        body: { title },
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: listKey }),
    onError: handleError.bind(showErrorToast),
  })

  const historyKey = useCallback(
    (id: string) => [
      "agent-session-messages",
      userId,
      agentKey,
      scopeType,
      scopeId,
      id,
    ],
    [agentKey, scopeId, scopeType, userId],
  )

  /** Stream a send through the unified endpoint; the assertion fields ride
   * along in the body (§4.3). Throws with the server's detail on 409/404. */
  const sendMessageStream = useCallback(
    (
      sessionId: string,
      content: string,
      opts: { onChunk: (t: string) => void; signal?: AbortSignal },
    ) => {
      const base = import.meta.env.VITE_API_URL ?? ""
      return streamChat(sessionId, content, {
        endpoint: `${base}/api/v1/agent-sessions/${sessionId}/messages/stream`,
        extraBody: {
          agent_key: agentKey,
          scope_type: scopeType,
          scope_id: scopeId,
        },
        ...opts,
      })
    },
    [agentKey, scopeId, scopeType],
  )

  /** After a finished turn: re-sync history from the checkpoint and refresh
   * the list/resolve (updated_at moved, auto-title may have appeared). */
  const afterTurn = useCallback(
    async (sessionId: string) => {
      await queryClient.invalidateQueries({ queryKey: historyKey(sessionId) })
      await queryClient.invalidateQueries({ queryKey: listKey })
    },
    [historyKey, listKey, queryClient],
  )

  return {
    sessions,
    currentSession,
    listPending: listQuery.isPending,
    createMutation,
    deleteMutation,
    renameMutation,
    selectSession,
    resetSelection,
    ensureSession,
    historyKey,
    sendMessageStream,
    afterTurn,
  }
}
