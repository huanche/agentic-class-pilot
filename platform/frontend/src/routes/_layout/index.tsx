import { useQuery } from "@tanstack/react-query"
import { createFileRoute, redirect } from "@tanstack/react-router"
import { ArrowUpRight, BookOpen, GraduationCap, ShieldCheck } from "lucide-react"
import { useState } from "react"

import { UsersService } from "@/client"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import useAuth from "@/hooks/useAuth"
import { teacherServiceUrl, usePlatformStatus } from "@/hooks/usePlatformStatus"

export const Route = createFileRoute("/_layout/")({
  component: Dashboard,
  beforeLoad: async () => {
    const user = (await UsersService.readUserMe()).data
    if (user.is_superuser) throw redirect({ to: "/admin" })
  },
})

type Course = { id: string; title: string; description?: string; enroll_code?: string }
type PublishedEntry = { title: string; content: string }

async function platformApi(path: string, init?: RequestInit) {
  const response = await fetch(`/api/v1${path}`, { credentials: "include", ...init })
  const data = await response.json()
  if (!response.ok) throw new Error(data.detail || "请求失败")
  return data
}

function Dashboard() {
  const { user } = useAuth()
  const teacher = user?.role === "teacher"
  const [error, setError] = useState("")
  const [opening, setOpening] = useState("")
  const [published, setPublished] = useState<PublishedEntry[] | null>(null)
  const status = usePlatformStatus()
  const courses = useQuery<{ data: Course[] }>({
    queryKey: ["dashboard-courses", teacher],
    queryFn: () => platformApi(teacher ? "/courses/" : "/enrollments/my-courses"),
    enabled: Boolean(user),
  })
  // The teacher service entry comes from backend configuration; never hardcode the port here.
  const courseCenterUrl = teacherServiceUrl(status.data?.teacherUrl, "/course-space")

  async function openCourse(course: Course) {
    setError("")
    setOpening(course.id)
    try {
      if (teacher) {
        const data = await platformApi(`/courses/${course.id}/teacher-workspace`, { method: "POST" })
        window.location.assign(data.url)
      } else {
        const data = await platformApi(`/courses/${course.id}/published-content`)
        setPublished(data.knowledgePackage?.entries || [])
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setOpening("")
    }
  }

  return <div className="space-y-8">
    <section className="rounded-2xl border bg-gradient-to-br from-[#B00055]/8 via-background to-blue-500/10 p-8">
      <p className="text-sm font-medium text-[#B00055]">AI 教育平台 · 统一工作空间</p>
      <h1 className="mt-3 text-3xl font-semibold">{user?.full_name || user?.email}，欢迎回来</h1>
      <p className="mt-3 text-muted-foreground">{teacher ? "进入教师课程中心创建课程并完成备课；在管理平台维护选课码与学生成员。" : "加入课程，查看教师发布的教学内容。"}</p>
      <div className="mt-6 flex flex-wrap gap-3">
        {teacher ? <>
          <Button asChild disabled={!courseCenterUrl}><a href={courseCenterUrl ?? "#"}>进入教师课程中心<ArrowUpRight className="ml-2 size-4" /></a></Button>
          <Button variant="outline" asChild><a href="/courses">课程管理</a></Button>
        </> : <Button asChild><a href="/join">使用选课码加入课程<ArrowUpRight className="ml-2 size-4" /></a></Button>}
      </div>
    </section>
    <div className="grid gap-4 md:grid-cols-3">
      <Card><CardHeader><CardTitle className="flex items-center gap-2 text-base"><BookOpen className="size-4" />我的课程</CardTitle></CardHeader><CardContent className="text-2xl font-semibold">{courses.data?.data.length ?? 0}</CardContent></Card>
      <Card><CardHeader><CardTitle className="flex items-center gap-2 text-base"><ShieldCheck className="size-4" />教师 Agent</CardTitle></CardHeader><CardContent>{status.data?.teacherReady ? "服务已就绪" : "服务连接中"}</CardContent></Card>
      <Card><CardHeader><CardTitle className="flex items-center gap-2 text-base"><GraduationCap className="size-4" />当前身份</CardTitle></CardHeader><CardContent>{user?.is_superuser ? "平台管理员" : teacher ? "教师" : "学生"}</CardContent></Card>
    </div>
    {error && <p role="alert" className="text-destructive">{error}</p>}
    {courses.error && <p role="alert" className="text-destructive">{courses.error.message}</p>}
    <section className="space-y-4">
      <h2 className="text-xl font-semibold">课程工作空间</h2>
      <div className="grid gap-4 md:grid-cols-2">{courses.data?.data.map((course) => <Card key={course.id}>
        <CardHeader><CardTitle>{course.title}</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">{course.description || "从课程目标出发，组织材料与教学内容。"}</p>
          {teacher && <p className="text-sm">学生选课码：<code>{course.enroll_code}</code></p>}
          <Button disabled={opening === course.id} onClick={() => openCourse(course)}>{opening === course.id ? "正在打开…" : teacher ? "进入教师工作区" : "查看已发布内容"}</Button>
        </CardContent>
      </Card>)}</div>
      {courses.data?.data.length === 0 && <p className="text-muted-foreground">{teacher ? "暂无课程，请前往教师课程中心创建。" : "还没有加入课程，请向教师获取选课码。"}</p>}
    </section>
    {published && <section className="space-y-4"><h2 className="text-xl font-semibold">已发布教学内容</h2>{published.length ? published.map((entry, index) => <Card key={index}><CardHeader><CardTitle>{entry.title}</CardTitle></CardHeader><CardContent><pre className="whitespace-pre-wrap font-sans text-sm leading-7">{entry.content}</pre></CardContent></Card>) : <p>教师尚未发布内容。</p>}</section>}
  </div>
}
