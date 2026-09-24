import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { BookOpen, ChevronRight, Users } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import useAuth from "@/hooks/useAuth"

type Course = { id: string; title: string; description?: string | null }
type Member = {
  id: string
  email: string
  full_name?: string | null
  enrolled_at: string
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

export const Route = createFileRoute("/_layout/students")({ component: Students })

function Students() {
  const { user } = useAuth()
  const teacher = user?.role === "teacher" || user?.is_superuser
  const courses = useQuery<{ data: Course[] }>({ queryKey: ["courses"], queryFn: () => api("/courses/"), enabled: teacher })
  if (!teacher) return <p className="text-muted-foreground">学生管理仅对教师开放。</p>
  return <div className="space-y-6">
    <div>
      <p className="text-sm font-medium text-[#B00055]">课程成员</p>
      <h1 className="text-3xl font-semibold tracking-tight">学生管理</h1>
      <p className="mt-2 text-muted-foreground">按课程查看已加入学生、章节学习进度与选课时间。</p>
    </div>
    <div className="grid gap-4 md:grid-cols-2">{courses.data?.data.map((course) => <RosterCard key={course.id} course={course} />)}</div>
    {courses.data?.data.length === 0 && <Card><CardContent className="p-8 text-center text-muted-foreground">请先创建课程。</CardContent></Card>}
  </div>
}

function RosterCard({ course }: { course: Course }) {
  const members = useQuery<Members>({ queryKey: ["course-members", course.id], queryFn: () => api(`/courses/${course.id}/members`) })
  return <Card className="transition hover:border-[#B00055]/30">
    <CardHeader>
      <CardTitle className="flex items-center gap-2">
        <BookOpen className="size-5 text-[#B00055]" />
        {course.title}
        <span className="ml-auto inline-flex items-center gap-1 text-sm font-normal text-muted-foreground">
          <Users className="size-4 text-[#B00055]" />
          {members.data?.count ?? "…"} 名学生
        </span>
      </CardTitle>
    </CardHeader>
    <CardContent className="space-y-3">
      <p className="text-sm text-muted-foreground">{course.description || "暂无课程简介"}</p>
      {members.data && members.data.data.length > 0 && (
        <ul className="divide-y rounded-xl border">
          {members.data.data.map((member) => (
            <li key={member.id} className="flex items-center justify-between gap-3 px-4 py-2.5 text-sm">
              <div className="min-w-0">
                <p className="truncate font-medium">{member.full_name || member.email}</p>
                {member.full_name && <p className="truncate text-xs text-muted-foreground">{member.email}</p>}
              </div>
              <div className="shrink-0 text-right">
                <p className="font-medium">{member.total_chapters > 0 ? `${member.completed_chapters}/${member.total_chapters} 章节` : "暂无章节"}</p>
                <p className="text-xs text-muted-foreground">加入于 {new Date(member.enrolled_at).toLocaleDateString()}</p>
              </div>
            </li>
          ))}
        </ul>
      )}
      {members.data && members.data.data.length === 0 && (
        <p className="rounded-xl bg-muted/50 px-4 py-3 text-sm text-muted-foreground">暂无学生加入，分享选课码即可邀请。</p>
      )}
      <Link to="/courses/$courseId" params={{ courseId: course.id }} className="inline-flex items-center text-sm font-medium text-[#B00055] hover:underline">
        管理本课程学生 <ChevronRight className="ml-1 size-4" />
      </Link>
    </CardContent>
  </Card>
}
