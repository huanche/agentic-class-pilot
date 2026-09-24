import { useSuspenseQuery } from "@tanstack/react-query"
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

function MyCoursesContent() {
  const { data: courses } = useSuspenseQuery({
    queryKey: ["my-courses"],
    queryFn: async () => (await EnrollmentsService.readMyCourses()).data,
  })

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
