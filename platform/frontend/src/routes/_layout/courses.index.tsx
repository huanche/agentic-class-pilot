import { useSuspenseQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { BookOpen, ExternalLink, Search } from "lucide-react"
import { Suspense } from "react"

import { CoursesService } from "@/client"
import PendingItems from "@/components/Pending/PendingItems"
import { Button } from "@/components/ui/button"
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { teacherServiceUrl, usePlatformStatus } from "@/hooks/usePlatformStatus"

function getCoursesQueryOptions() {
  return {
    queryFn: async () => (await CoursesService.readCourses({ query: { skip: 0, limit: 100 } })).data,
    queryKey: ["courses"],
  }
}

export const Route = createFileRoute("/_layout/courses/")({
  component: Courses,
  head: () => ({ meta: [{ title: "课程管理 - AI 教育平台" }] }),
})

function CoursesListContent() {
  const { data: courses } = useSuspenseQuery(getCoursesQueryOptions())
  if (courses.data.length === 0) return <div className="flex flex-col items-center justify-center py-12 text-center">
    <div className="mb-4 rounded-full bg-muted p-4"><Search className="h-8 w-8 text-muted-foreground" /></div>
    <h3 className="text-lg font-semibold">暂无课程</h3>
    <p className="text-muted-foreground">请前往教师课程中心创建课程。</p>
  </div>
  return <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">{courses.data.map((course) => <Card key={course.id} className="h-full transition-colors hover:bg-muted/50">
    <CardHeader>
      <Link to="/courses/$courseId" params={{ courseId: course.id }} className="min-w-0">
        <CardTitle className="flex items-center gap-2"><BookOpen className="h-5 w-5 shrink-0 text-[#B00055]" /><span className="truncate">{course.title}</span></CardTitle>
        <CardDescription className="mt-1 line-clamp-2">{course.description || "暂无简介"}</CardDescription>
      </Link>
    </CardHeader>
  </Card>)}</div>
}

function Courses() {
  // The teacher service entry comes from backend configuration; never hardcode the port here.
  const status = usePlatformStatus()
  const courseCenterUrl = teacherServiceUrl(status.data?.teacherUrl, "/course-space")
  return <div className="flex flex-col gap-6">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div><h1 className="text-2xl font-bold tracking-tight">课程管理</h1><p className="text-muted-foreground">选择课程，管理选课学生并查看学习情况</p></div>
      <Button asChild disabled={!courseCenterUrl}><a href={courseCenterUrl ?? "#"}>进入教师课程中心<ExternalLink className="ml-2 size-4" /></a></Button>
    </div>
    <Suspense fallback={<PendingItems />}><CoursesListContent /></Suspense>
  </div>
}
