import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { BookOpen, CircleAlert } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import useAuth from "@/hooks/useAuth"
import { usePlatformStatus } from "@/hooks/usePlatformStatus"

type Course = { id: string; title: string }
type Member = {
  id: string
  email: string
  full_name?: string | null
  completed_chapters: number
  total_chapters: number
}
type Members = { data: Member[]; count: number }

type ClassroomLearningData = {
  sessions: Array<{
    sessionKey: string
    userId: string
    classroomId: string | null
    startedAt: string
    lastActiveAt: string
    ended: boolean
  }>
  mastery: Array<{ userId: string; knowledgePointId: string; stars: number; status: string }>
  eventSummary: Record<string, number>
}

async function api<T>(path: string): Promise<T> {
  const response = await fetch(`/api/v1${path}`, { credentials: "include" })
  const data = await response.json()
  if (!response.ok) throw new Error(data.detail || "请求失败")
  return data
}

export const Route = createFileRoute("/_layout/learning-data")({ component: LearningData })

/**
 * 学习数据页：选课关系、章节完成记录，以及学生 Agent 落库的课堂学情
 * （课堂会话、知识点掌握度、事件统计 —— 全部为真实落库数据）。
 */
function LearningData() {
  const { user } = useAuth()
  const teacher = user?.role === "teacher" || user?.is_superuser
  const status = usePlatformStatus()
  const courses = useQuery<{ data: Course[] }>({ queryKey: ["courses"], queryFn: () => api("/courses/"), enabled: teacher })
  if (!teacher) return <p className="text-muted-foreground">学习数据仅对教师开放。</p>

  const studentAgentReady = status.data?.studentAgentReady === true

  return <div className="space-y-6">
    <div>
      <p className="text-sm font-medium text-[#B00055]">学习分析</p>
      <h1 className="text-3xl font-semibold tracking-tight">学习数据</h1>
      <p className="mt-2 text-muted-foreground">课程学习进度总览与课堂学情（学生 Agent 每节课自动同步）。</p>
    </div>

    {!studentAgentReady && (
      <Card className="border-dashed">
        <CardContent className="flex items-start gap-3 p-6">
          <CircleAlert className="mt-0.5 size-5 shrink-0 text-amber-500" />
          <div className="space-y-1">
            <p className="font-medium">学生 Agent 暂不可用</p>
            <p className="text-sm text-muted-foreground">
              课堂会话、发言记录、知识点掌握度等数据由学生 Agent 在课堂中写入统一数据库。
              学生 Agent 离线期间不产生新数据，已有数据仍正常展示。
            </p>
          </div>
        </CardContent>
      </Card>
    )}

    <div className="grid gap-4 md:grid-cols-2">
      {courses.data?.data.map((course) => <CourseProgressCard key={course.id} course={course} />)}
    </div>
    {courses.data?.data.length === 0 && (
      <Card><CardContent className="p-8 text-center text-muted-foreground">请先创建课程。</CardContent></Card>
    )}
  </div>
}

type SessionRow = ClassroomLearningData["sessions"][number]

function CourseProgressCard({ course }: { course: Course }) {
  const members = useQuery<Members>({ queryKey: ["course-members", course.id], queryFn: () => api(`/courses/${course.id}/members`) })
  const roster = members.data?.data ?? []
  const withProgress = roster.filter((member) => member.total_chapters > 0)
  const classroom = useQuery<ClassroomLearningData>({
    queryKey: ["course-classroom-learning", course.id],
    queryFn: () => api(`/courses/${course.id}/learning-data`),
    refetchInterval: 60_000,
  })
  const nameByUser = new Map(roster.map((m) => [m.id, m.full_name || m.email]))
  const sessions = (classroom.data?.sessions ?? []).slice(0, 5)
  const starsByUser = new Map<string, number>()
  for (const row of classroom.data?.mastery ?? []) {
    starsByUser.set(row.userId, (starsByUser.get(row.userId) ?? 0) + (row.stars ?? 0))
  }
  const eventSummary = classroom.data?.eventSummary ?? {}

  return <Card>
    <CardHeader>
      <CardTitle className="flex items-center gap-2">
        <BookOpen className="size-5 text-[#B00055]" />
        {course.title}
        <span className="ml-auto text-sm font-normal text-muted-foreground">{members.data?.count ?? "…"} 名学生</span>
      </CardTitle>
    </CardHeader>
    <CardContent className="space-y-3">
      {roster.length === 0 && <p className="text-sm text-muted-foreground">暂无学生加入。</p>}
      {withProgress.length === 0 && roster.length > 0 && (
        <p className="text-sm text-muted-foreground">课程暂无章节，无进度记录。</p>
      )}
      {withProgress.map((member) => {
        const percent = member.total_chapters > 0 ? Math.round((member.completed_chapters / member.total_chapters) * 100) : 0
        return <div key={member.id} className="space-y-1">
          <div className="flex items-center justify-between text-sm">
            <span className="truncate">{member.full_name || member.email}</span>
            <span className="text-muted-foreground">{member.completed_chapters}/{member.total_chapters} 章节 · {percent}%</span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-muted">
            <div className="h-full rounded-full bg-[#B00055]/70" style={{ width: `${percent}%` }} />
          </div>
        </div>
      })}

      {classroom.data && (sessions.length > 0 || Object.keys(eventSummary).length > 0) && (
        <div className="rounded-lg border bg-muted/30 p-3 space-y-2">
          <p className="text-xs font-medium text-muted-foreground">课堂学情（学生 Agent 实时同步）</p>
          {roster.map((member) => {
            const stars = starsByUser.get(member.id)
            return stars ? (
              <div key={`m-${member.id}`} className="flex items-center justify-between text-xs">
                <span className="truncate">{member.full_name || member.email}</span>
                <span className="text-amber-500">★ {stars}</span>
              </div>
            ) : null
          })}
          {sessions.map((session: SessionRow) => (
            <div key={session.sessionKey} className="flex items-center justify-between gap-2 text-xs">
              <span className="truncate">{nameByUser.get(session.userId) ?? session.userId.slice(0, 8)}</span>
              <span className="shrink-0 text-muted-foreground">
                {session.ended ? "已完成" : "学习中"} ·{" "}
                {new Date(session.lastActiveAt).toLocaleString("zh-CN", {
                  month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit",
                })}
              </span>
            </div>
          ))}
          <p className="text-xs text-muted-foreground">
            {Object.entries(eventSummary).map(([type, count]) => `${type} ${count}`).join(" · ")}
          </p>
        </div>
      )}
    </CardContent>
  </Card>
}
