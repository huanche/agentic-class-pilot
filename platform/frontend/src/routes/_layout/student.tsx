import { useQuery } from "@tanstack/react-query"
import { createFileRoute, redirect } from "@tanstack/react-router"
import { BookOpen, CircleAlert, Hourglass, PlayCircle } from "lucide-react"
import { useState } from "react"

import { UsersService } from "@/client"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import useAuth from "@/hooks/useAuth"
import { usePlatformStatus } from "@/hooks/usePlatformStatus"

export const Route = createFileRoute("/_layout/student")({
  component: StudentHome,
  beforeLoad: async () => {
    const user = (await UsersService.readUserMe()).data
    if (user.role === "teacher" && !user.is_superuser) {
      throw redirect({ to: "/teacher" })
    }
  },
  head: () => ({ meta: [{ title: "学生首页 - AI 教育平台" }] }),
})

type EnrolledCourse = {
  id: string
  title: string
  description?: string | null
  completed_chapters?: number
  total_chapters?: number
}
type PublishedEntry = { title: string; content?: string }
type PublishedContent = {
  knowledgePackage: { version?: number; entries?: PublishedEntry[] } | null
  classroomAvailable: boolean
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/v1${path}`, { credentials: "include", ...init })
  const data = await response.json()
  if (!response.ok) throw new Error(data.detail || "请求失败")
  return data
}

function StudentHome() {
  const { user } = useAuth()
  const status = usePlatformStatus()
  const courses = useQuery<{ data: EnrolledCourse[] }>({
    queryKey: ["my-courses"],
    queryFn: () => api("/enrollments/my-courses"),
  })
  const studentAgentReady = status.data?.studentAgentReady === true

  async function enterCourse(courseId: string) {
    // Trusted entry only: the platform backend returns the signed launch URL;
    // the frontend never assembles the student-agent address itself.
    const data = await api<{ url: string }>(`/courses/${courseId}/student-workspace`, { method: "POST" })
    window.location.assign(data.url)
  }

  return <div className="space-y-6">
    <div>
      <p className="text-sm font-medium text-[#B00055]">学生学习空间</p>
      <h1 className="text-3xl font-semibold tracking-tight">学生首页</h1>
      <p className="mt-2 text-muted-foreground">{user?.full_name || user?.email}，查看你的课程并开始学习。</p>
    </div>
    {!studentAgentReady && (
      <Card className="border-dashed">
        <CardContent className="flex items-start gap-3 p-6">
          <CircleAlert className="mt-0.5 size-5 shrink-0 text-amber-500" />
          <div className="space-y-1">
            <p className="font-medium">学生 Agent 服务暂不可用</p>
            <p className="text-sm text-muted-foreground">已发布课程的学习入口暂时无法打开，请稍后再试。</p>
          </div>
        </CardContent>
      </Card>
    )}
    <div className="grid gap-4 md:grid-cols-2">
      {courses.data?.data.map((course) => <CourseCard key={course.id} course={course} onEnter={enterCourse} />)}
    </div>
    {courses.data?.data.length === 0 && (
      <Card><CardContent className="p-8 text-center text-muted-foreground">还没有加入课程，请到「加入课程」使用选课码。</CardContent></Card>
    )}
  </div>
}

function CourseCard({ course, onEnter }: { course: EnrolledCourse; onEnter: (courseId: string) => Promise<void> }) {
  const [opening, setOpening] = useState(false)
  const [entryError, setEntryError] = useState<string | null>(null)
  const published = useQuery<PublishedContent>({
    queryKey: ["published-content", course.id],
    queryFn: () => api(`/courses/${course.id}/published-content`),
  })
  const packageData = published.data?.knowledgePackage
  const hasPackage = packageData != null
  const canEnter = hasPackage && published.data?.classroomAvailable === true

  async function handleEnter() {
    if (opening) return
    setOpening(true)
    setEntryError(null)
    try {
      await onEnter(course.id)
    } catch (error) {
      setEntryError(error instanceof Error ? error.message : "进入学习失败，请稍后重试")
      setOpening(false)
    }
  }

  return <Card>
    <CardHeader>
      <CardTitle className="flex items-center gap-2">
        <BookOpen className="size-5 text-[#B00055]" />
        {course.title}
      </CardTitle>
    </CardHeader>
    <CardContent className="space-y-3">
      <p className="text-sm text-muted-foreground">{course.description || "跟随课堂计划完成学习。"}</p>
      {canEnter
        ? <Button disabled={opening} onClick={handleEnter}>
            <PlayCircle className="mr-2 size-4" />{opening ? "正在进入…" : "进入学习"}
          </Button>
        : <p className="inline-flex items-center gap-2 rounded-xl bg-muted/60 px-4 py-2 text-sm text-muted-foreground">
            <Hourglass className="size-4" />{hasPackage ? "教师正在准备互动授课课件" : "等待教师发布"}
          </p>}
      {entryError && <p role="alert" className="text-sm text-destructive">{entryError}</p>}
      {hasPackage && <div className="rounded-xl border bg-muted/20 p-3 text-sm">
        <p className="font-medium">已发布学习资料</p>
        <div className="mt-2 space-y-2 text-muted-foreground">
          {(packageData.entries ?? []).map((entry, index) => <details key={index} className="rounded-lg bg-background px-3 py-2">
            <summary className="cursor-pointer font-medium text-foreground">{entry.title}</summary>
            <p className="mt-2 whitespace-pre-wrap leading-6">{entry.content || "该资料暂无可展示正文。"}</p>
          </details>)}
        </div>
      </div>}
    </CardContent>
  </Card>
}
