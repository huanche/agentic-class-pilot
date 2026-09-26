import { useQuery, useSuspenseQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { GraduationCap, Search } from "lucide-react"
import { Suspense } from "react"

import { EnrollmentsService } from "@/client"
import PendingItems from "@/components/Pending/PendingItems"
import {
  Card,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"

export const Route = createFileRoute("/_layout/my-courses")({
  component: MyCourses,
  head: () => ({
    meta: [{ title: "我的课程 - AI 教育平台" }],
  }),
})

type LearningSummary = {
  courseId: string
  courseTitle: string
  totalLessons: number
  learnedLessons: number
  endedSessions: number
  lastActiveAt: string | null
  stars: number
  percent: number
}

/** 学生端课堂学情（student agent 落库的真实数据，随每节课开始/结束更新）。 */
function useLearningSummary(enabled: boolean) {
  return useQuery<LearningSummary[]>({
    queryKey: ["my-learning-summary"],
    queryFn: async () => {
      const response = await fetch("/api/v1/users/me/learning-summary", {
        credentials: "include",
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || "请求失败")
      return data.courses
    },
    enabled,
    refetchInterval: 30_000,
  })
}

function formatLastActive(value: string | null): string {
  if (!value) return "尚未进入课堂"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return "尚未进入课堂"
  return `最近学习 ${date.toLocaleString("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })}`
}

function MyCoursesContent() {
  const { data: courses } = useSuspenseQuery({
    queryKey: ["my-courses"],
    queryFn: async () => (await EnrollmentsService.readMyCourses()).data,
  })
  const summary = useLearningSummary(courses.data.length > 0)
  const summaryByCourse = new Map(
    (summary.data ?? []).map((item) => [item.courseId, item]),
  )

  if (courses.data.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center text-center py-12">
        <div className="rounded-full bg-muted p-4 mb-4">
          <Search className="h-8 w-8 text-muted-foreground" />
        </div>
        <h3 className="text-lg font-semibold">还没有加入任何课程</h3>
        <p className="text-muted-foreground">
          去「加入课程」页面输入选课码开始学习
        </p>
      </div>
    )
  }

  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
      {courses.data.map((course) => {
        const total = course.total_chapters ?? 0
        const done = course.completed_chapters ?? 0
        const pct = total > 0 ? Math.round((done / total) * 100) : 0
        const progress = summaryByCourse.get(course.id)
        return (
          <Link
            key={course.id}
            to="/courses/$courseId"
            params={{ courseId: course.id }}
          >
            <Card className="hover:bg-muted/50 transition-colors h-full">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <GraduationCap className="h-5 w-5 text-muted-foreground" />
                  <span className="truncate">{course.title}</span>
                </CardTitle>
                <CardDescription className="line-clamp-2">
                  {course.description || "暂无简介"}
                </CardDescription>
                <div className="pt-2">
                  <div className="flex justify-between text-xs text-muted-foreground mb-1">
                    <span>学习进度</span>
                    <span>
                      {done}/{total} 章 · {pct}%
                    </span>
                  </div>
                  <div className="h-2 rounded-full bg-muted overflow-hidden">
                    <div
                      className="h-full rounded-full bg-primary transition-all"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  {progress && (progress.totalLessons > 0 || progress.lastActiveAt) && (
                    <div className="mt-3 flex items-center justify-between text-xs text-muted-foreground">
                      <span>
                        课堂学习 {progress.learnedLessons}/{progress.totalLessons} 节
                        {progress.stars > 0 ? ` · ★ ${progress.stars}` : ""}
                      </span>
                      <span className="truncate ml-2">
                        {formatLastActive(progress.lastActiveAt)}
                      </span>
                    </div>
                  )}
                </div>
              </CardHeader>
            </Card>
          </Link>
        )
      })}
    </div>
  )
}

function MyCourses() {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">我的课程</h1>
        <p className="text-muted-foreground">你已加入的课程和学习进度</p>
      </div>
      <Suspense fallback={<PendingItems />}>
        <MyCoursesContent />
      </Suspense>
    </div>
  )
}
