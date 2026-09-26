import { useQuery } from "@tanstack/react-query"
import { BookOpen } from "lucide-react"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

type Member = {
  id: string
  email: string
  full_name?: string | null
}

type ClassroomLearningData = {
  publishedLessons: number
  sessions: Array<{
    sessionKey: string
    userId: string
    classroomId: string | null
    startedAt: string
    lastActiveAt: string
    ended: boolean
  }>
  mastery: Array<{
    userId: string
    knowledgePointId: string
    stars: number
    status: string
  }>
  eventSummary: Record<string, number>
}

type StudentRow = {
  id: string
  name: string
  status: "未开始" | "学习中" | "已完成"
  learned: number
  total: number
  percent: number
  sessionCount: number
  endedCount: number
  stars: number
  lastActive: string | null
}

async function api<T>(path: string): Promise<T> {
  const response = await fetch(`/api/v1${path}`, { credentials: "include" })
  const data = await response.json()
  if (!response.ok) throw new Error(data.detail || "请求失败")
  return data
}

function formatTime(value: string | null): string {
  if (!value) return "—"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return "—"
  return date.toLocaleString("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

/**
 * 课堂学情面板（教师视角）：每名学生的课堂进度、会话数、知识点星级与
 * 最近活跃。数据全部来自学生 Agent 落库的 student schema，随课堂
 * 开始/结束实时更新。
 */
export function ClassroomLearningPanel({ courseId }: { courseId: string }) {
  const members = useQuery<{ data: Member[] }>({
    queryKey: ["course-members", courseId],
    queryFn: () => api<{ data: Member[] }>(`/courses/${courseId}/members`),
    refetchInterval: 60_000,
  })
  const learning = useQuery<ClassroomLearningData>({
    queryKey: ["course-classroom-learning", courseId],
    queryFn: () => api(`/courses/${courseId}/learning-data`),
    refetchInterval: 60_000,
  })

  const roster = members.data?.data ?? []
  const data = learning.data
  const total = data?.publishedLessons ?? 0

  const rows: StudentRow[] = roster.map((member) => {
    const sessions = (data?.sessions ?? []).filter((s) => s.userId === member.id)
    const learned = new Set(
      sessions.map((s) => s.classroomId).filter(Boolean),
    ).size
    const stars = (data?.mastery ?? [])
      .filter((m) => m.userId === member.id)
      .reduce((sum, m) => sum + (m.stars ?? 0), 0)
    const lastActive = sessions.reduce<string | null>((latest, s) => {
      return !latest || s.lastActiveAt > latest ? s.lastActiveAt : latest
    }, null)
    const percent = total > 0 ? Math.min(100, Math.round((learned / total) * 100)) : 0
    const status: StudentRow["status"] =
      sessions.length === 0
        ? "未开始"
        : total > 0 && learned >= total
          ? "已完成"
          : "学习中"
    return {
      id: member.id,
      name: member.full_name || member.email,
      status,
      learned,
      total,
      percent,
      sessionCount: sessions.length,
      endedCount: sessions.filter((s) => s.ended).length,
      stars,
      lastActive,
    }
  })
  // 有课堂记录的学生排前面，再按进度倒序
  rows.sort((a, b) => {
    if (a.sessionCount === 0 !== (b.sessionCount === 0)) {
      return a.sessionCount === 0 ? 1 : -1
    }
    return b.percent - a.percent || b.stars - a.stars
  })

  const hasData = !!data && data.sessions.length > 0

  return (
    <Card className="border-[#B00055]/15">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <BookOpen className="size-5 text-[#B00055]" />
          课堂学情
          <span className="ml-auto text-sm font-normal text-muted-foreground">
            已发布 {total} 节课时{data ? ` · ${roster.length} 名学生` : ""}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {learning.isLoading && (
          <p className="text-sm text-muted-foreground">学情载入中…</p>
        )}
        {!learning.isLoading && !hasData && (
          <p className="text-sm text-muted-foreground">
            暂无课堂学习数据。学生进入课堂开始学习后，这里会展示每名学生的课时进度、
            会话数与知识点星级（学生 Agent 每节课自动同步）。
          </p>
        )}
        {hasData && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th className="py-2 pr-3 font-medium">学生</th>
                  <th className="py-2 pr-3 font-medium">状态</th>
                  <th className="py-2 pr-3 font-medium">课堂进度</th>
                  <th className="py-2 pr-3 font-medium">会话</th>
                  <th className="py-2 pr-3 font-medium">知识点星级</th>
                  <th className="py-2 font-medium">最近活跃</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id} className="border-b last:border-0">
                    <td className="max-w-36 truncate py-2.5 pr-3">{row.name}</td>
                    <td className="py-2.5 pr-3">
                      <span
                        className={
                          "inline-flex rounded-full px-2 py-0.5 text-xs " +
                          (row.status === "已完成"
                            ? "bg-emerald-500/10 text-emerald-600"
                            : row.status === "学习中"
                              ? "bg-blue-500/10 text-blue-600"
                              : "bg-muted text-muted-foreground")
                        }
                      >
                        {row.status}
                      </span>
                    </td>
                    <td className="py-2.5 pr-3">
                      <div className="flex min-w-32 items-center gap-2">
                        <div className="h-1.5 w-24 overflow-hidden rounded-full bg-muted">
                          <div
                            className="h-full rounded-full bg-[#B00055]/70"
                            style={{ width: `${row.percent}%` }}
                          />
                        </div>
                        <span className="shrink-0 text-xs text-muted-foreground">
                          {row.learned}/{row.total} 节
                        </span>
                      </div>
                    </td>
                    <td className="py-2.5 pr-3 text-xs text-muted-foreground">
                      {row.sessionCount} 次 · 完成 {row.endedCount}
                    </td>
                    <td className="py-2.5 pr-3 text-xs">
                      {row.stars > 0 ? (
                        <span className="text-amber-500">★ {row.stars}</span>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </td>
                    <td className="py-2.5 text-xs text-muted-foreground">
                      {formatTime(row.lastActive)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {hasData && data && Object.keys(data.eventSummary).length > 0 && (
          <p className="text-xs text-muted-foreground">
            课堂事件统计：
            {Object.entries(data.eventSummary)
              .map(([type, count]) => `${type} ${count} 次`)
              .join(" · ")}
          </p>
        )}
      </CardContent>
    </Card>
  )
}
