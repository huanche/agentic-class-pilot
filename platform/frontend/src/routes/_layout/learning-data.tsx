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

async function api<T>(path: string): Promise<T> {
  const response = await fetch(`/api/v1${path}`, { credentials: "include" })
  const data = await response.json()
  if (!response.ok) throw new Error(data.detail || "请求失败")
  return data
}

export const Route = createFileRoute("/_layout/learning-data")({ component: LearningData })

/**
 * 学习数据页只展示真实已有数据。学生 Agent（课堂会话、播放事件、知识点掌握度）
 * 尚未接入时给出明确空状态；平台侧现有数据仅为选课关系与章节完成记录。
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
      <p className="mt-2 text-muted-foreground">课程学习进度总览；课堂会话与掌握度数据将在学生 Agent 接入后展示。</p>
    </div>

    {!studentAgentReady && (
      <Card className="border-dashed">
        <CardContent className="flex items-start gap-3 p-6">
          <CircleAlert className="mt-0.5 size-5 shrink-0 text-amber-500" />
          <div className="space-y-1">
            <p className="font-medium">学生 Agent 尚未接入</p>
            <p className="text-sm text-muted-foreground">
              课堂会话、发言记录、播放事件、阶段进度与知识点掌握度等数据由学生 Agent 写入统一数据库后才会出现在这里。
              当前页面仅展示平台已有真实数据（选课关系与章节完成记录），不提供模拟统计。
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

function CourseProgressCard({ course }: { course: Course }) {
  const members = useQuery<Members>({ queryKey: ["course-members", course.id], queryFn: () => api(`/courses/${course.id}/members`) })
  const roster = members.data?.data ?? []
  const withProgress = roster.filter((member) => member.total_chapters > 0)
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
    </CardContent>
  </Card>
}
