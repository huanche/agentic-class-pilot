import { useSuspenseQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { ArrowLeft, Copy, ExternalLink } from "lucide-react"
import { Suspense, useState } from "react"

import { CoursesService } from "@/client"
import { CourseMembersPanel } from "@/components/Courses/CourseMembersPanel"
import { ClassroomLearningPanel } from "@/components/Courses/ClassroomLearningPanel"
import PendingItems from "@/components/Pending/PendingItems"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import useAuth from "@/hooks/useAuth"
import useCustomToast from "@/hooks/useCustomToast"

export const Route = createFileRoute("/_layout/courses/$courseId")({
  component: CourseDetail,
  head: () => ({ meta: [{ title: "课程管理 - AI 教育平台" }] }),
})

async function openTeacherWorkspace(courseId: string) {
  const response = await fetch(`/api/v1/courses/${courseId}/teacher-workspace`, {
    method: "POST",
    credentials: "include",
  })
  const data = await response.json()
  if (!response.ok) throw new Error(data.detail || "无法打开教师工作区")
  window.location.assign(data.url)
}

async function openStudentWorkspace(courseId: string) {
  // 与学生首页同一个可信入口：平台签发带 launch_token 的学习地址
  const response = await fetch(`/api/v1/courses/${courseId}/student-workspace`, {
    method: "POST",
    credentials: "include",
  })
  const data = await response.json()
  if (!response.ok) throw new Error(data.detail || "进入学习失败")
  window.location.assign(data.url)
}

function StudentChapters({ courseId }: { courseId: string }) {
  const { data: chapters } = useSuspenseQuery({
    queryKey: ["chapters", courseId],
    queryFn: async () => (
      await CoursesService.readChapters({
        path: { course_id: courseId },
        query: { skip: 0, limit: 100 },
      })
    ).data,
  })

  return (
    <Card>
      <CardHeader><CardTitle>课程章节</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        {chapters.data.length ? chapters.data.map((chapter) => (
          <div key={chapter.id} className="rounded-lg border p-3">
            <p className="font-medium">{(chapter.order_index ?? 0) + 1}. {chapter.title}</p>
            {chapter.description && <p className="mt-1 text-sm text-muted-foreground">{chapter.description}</p>}
          </div>
        )) : <p className="text-sm text-muted-foreground">暂无课程章节。</p>}
      </CardContent>
    </Card>
  )
}

function CourseDetail() {
  const { courseId } = Route.useParams()
  const { user } = useAuth()
  const teacher = user?.role === "teacher" || user?.is_superuser === true
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [opening, setOpening] = useState(false)
  const [entering, setEntering] = useState(false)

  async function handleEnterLearning() {
    setEntering(true)
    try {
      await openStudentWorkspace(courseId)
    } catch (error) {
      showErrorToast(error instanceof Error ? error.message : "进入学习失败，请稍后重试")
      setEntering(false)
    }
  }
  const { data: course } = useSuspenseQuery({
    queryKey: ["courses", courseId],
    queryFn: async () => (await CoursesService.readCourse({ path: { course_id: courseId } })).data,
  })

  async function handleOpenWorkspace() {
    setOpening(true)
    try {
      await openTeacherWorkspace(courseId)
    } catch (error) {
      showErrorToast(error instanceof Error ? error.message : "无法打开教师工作区")
      setOpening(false)
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <Link to={teacher ? "/courses" : "/my-courses"} className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
            <ArrowLeft className="h-4 w-4" />返回课程列表
          </Link>
          <div className="mt-2 flex items-center gap-2">
            <h1 className="text-2xl font-bold tracking-tight">{course.title}</h1>
          </div>
          {course.description && <p className="mt-1 text-muted-foreground">{course.description}</p>}
          {teacher && course.enroll_code && (
            <button type="button" className="mt-3 inline-flex items-center gap-2 rounded-md border px-2.5 py-1 text-sm font-mono tracking-widest hover:bg-muted" onClick={() => { navigator.clipboard.writeText(course.enroll_code ?? ""); showSuccessToast("选课码已复制") }}>
              选课码：{course.enroll_code}<Copy className="h-3.5 w-3.5 text-muted-foreground" />
            </button>
          )}
        </div>
        {teacher && <Button disabled={opening} onClick={handleOpenWorkspace}>{opening ? "正在打开…" : "进入教师工作区"}<ExternalLink className="ml-2 h-4 w-4" /></Button>}
        {!teacher && <Button disabled={entering} onClick={handleEnterLearning}>{entering ? "正在进入…" : "进入学习"}</Button>}
      </div>

      {teacher ? <>
        <ClassroomLearningPanel courseId={courseId} />
        <CourseMembersPanel courseId={courseId} enrollCode={course.enroll_code} />
      </> : <Suspense fallback={<PendingItems />}><StudentChapters courseId={courseId} /></Suspense>}
    </div>
  )
}
