import { createFileRoute, redirect } from "@tanstack/react-router"
import {
  ArrowRight,
  BookOpenCheck,
  Bot,
  CheckCircle2,
  Presentation,
  ShieldCheck,
  Sparkles,
} from "lucide-react"

import { UsersService } from "@/client"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import useAuth from "@/hooks/useAuth"
import { teacherServiceUrl, usePlatformStatus } from "@/hooks/usePlatformStatus"

export const Route = createFileRoute("/_layout/teacher")({
  component: TeacherPortal,
  beforeLoad: async () => {
    const user = (await UsersService.readUserMe()).data
    if (user.is_superuser && user.role !== "teacher") {
      throw redirect({ to: "/admin" })
    }
    if (user.role !== "teacher") {
      throw redirect({ to: "/" })
    }
  },
  head: () => ({ meta: [{ title: "教师工作空间 - AI 教育平台" }] }),
})

type ProductCardProps = {
  eyebrow: string
  title: string
  description: string
  features: string[]
  href?: string
  icon: typeof BookOpenCheck
  accent: "primary" | "blue"
}

function ProductCard({
  eyebrow,
  title,
  description,
  features,
  href,
  icon: Icon,
  accent,
}: ProductCardProps) {
  const primary = accent === "primary"
  return (
    <Card className="group relative overflow-hidden border-border/70 bg-background/95 shadow-sm transition duration-300 hover:-translate-y-1 hover:shadow-xl">
      <div
        className={`absolute inset-x-0 top-0 h-1 ${primary ? "bg-[#B00055]" : "bg-blue-600"}`}
      />
      <CardHeader className="space-y-5 p-7 pb-3">
        <div className="flex items-start justify-between gap-4">
          <div
            className={`grid size-12 place-items-center rounded-2xl ${primary ? "bg-[#B00055]/10 text-[#B00055]" : "bg-blue-600/10 text-blue-700"}`}
          >
            <Icon className="size-6" />
          </div>
          <span className="rounded-full border bg-background px-3 py-1 text-xs text-muted-foreground">
            教师 Agent
          </span>
        </div>
        <div>
          <p
            className={`text-xs font-semibold tracking-[0.16em] ${primary ? "text-[#B00055]" : "text-blue-700"}`}
          >
            {eyebrow}
          </p>
          <CardTitle className="mt-2 text-2xl">{title}</CardTitle>
          <p className="mt-3 min-h-12 text-sm leading-6 text-muted-foreground">
            {description}
          </p>
        </div>
      </CardHeader>
      <CardContent className="space-y-6 p-7 pt-3">
        <ul className="grid gap-2.5 text-sm text-foreground/80 sm:grid-cols-2">
          {features.map((feature) => (
            <li key={feature} className="flex items-center gap-2">
              <CheckCircle2
                className={`size-4 shrink-0 ${primary ? "text-[#B00055]" : "text-blue-600"}`}
              />
              {feature}
            </li>
          ))}
        </ul>
        <Button
          asChild={Boolean(href)}
          disabled={!href}
          className={`w-full justify-between ${primary ? "bg-[#B00055] hover:bg-[#8F0046]" : "bg-blue-700 hover:bg-blue-800"}`}
        >
          {href ? (
            <a href={href}>
              进入{title}
              <ArrowRight className="size-4" />
            </a>
          ) : (
            <span>
              教师服务连接中
              <ArrowRight className="size-4" />
            </span>
          )}
        </Button>
      </CardContent>
    </Card>
  )
}

function TeacherPortal() {
  const { user } = useAuth()
  const status = usePlatformStatus()
  const courseBuilding = teacherServiceUrl(
    status.data?.teacherUrl,
    "/course-space",
  )
  const classTeaching = teacherServiceUrl(status.data?.teacherUrl, "/classes")

  return (
    <div className="space-y-8 pb-8">
      <section className="relative overflow-hidden rounded-[28px] border bg-gradient-to-br from-[#B00055]/10 via-background to-blue-600/10 px-7 py-10 md:px-10">
        <div className="absolute -right-16 -top-20 size-64 rounded-full bg-[#B00055]/10 blur-3xl" />
        <div className="relative max-w-3xl">
          <div className="mb-5 flex flex-wrap items-center gap-2 text-xs font-medium">
            <span className="rounded-full bg-[#B00055]/10 px-3 py-1.5 text-[#B00055]">
              AI 教育平台
            </span>
            <span className="flex items-center gap-1.5 rounded-full border bg-background/80 px-3 py-1.5 text-muted-foreground">
              <ShieldCheck className="size-3.5" />
              可信教师身份
            </span>
            <span className="flex items-center gap-1.5 rounded-full border bg-background/80 px-3 py-1.5 text-muted-foreground">
              <Bot className="size-3.5" />
              {status.data?.teacherReady
                ? "教师 Agent 已就绪"
                : "正在连接教师 Agent"}
            </span>
          </div>
          <p className="text-sm font-medium text-[#B00055]">教师产品工作空间</p>
          <h1 className="mt-3 text-3xl font-semibold tracking-tight md:text-4xl">
            {user?.full_name || user?.email}，欢迎回来
          </h1>
          <p className="mt-4 max-w-2xl text-base leading-7 text-muted-foreground">
            从课程建设开始组织材料、完成 AI
            辅助备课和内容发布；进入授课管理查看已发布课程、教学资料与学生学习状态。
          </p>
        </div>
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <ProductCard
          eyebrow="COURSE DEVELOPMENT"
          title="课程建设"
          description="围绕课程目标组织教学材料，通过教师 Agent 完成备课、生成、审核与发布。"
          features={[
            "创建课程与课程结构",
            "上传并解析教学材料",
            "AI 辅助备课与内容生成",
            "审核并发布教学内容",
          ]}
          href={courseBuilding}
          icon={BookOpenCheck}
          accent="primary"
        />
        <ProductCard
          eyebrow="TEACHING MANAGEMENT"
          title="授课管理"
          description="集中查看正在授课的课程、已发布资料、播放器内容以及学生学习状态。"
          features={[
            "已发布课程与 Class",
            "授课资料与产物",
            "播放器与课堂预览",
            "学生名单与学习进度",
          ]}
          href={classTeaching}
          icon={Presentation}
          accent="blue"
        />
      </div>

      <div className="flex items-center gap-3 rounded-2xl border bg-muted/30 px-5 py-4 text-sm text-muted-foreground">
        <Sparkles className="size-5 shrink-0 text-[#B00055]" />
        课程、成员和学习数据仍由平台统一鉴权与管理；此页面只提供教师产品入口，不重复实现教师
        Agent 的业务功能。
      </div>
    </div>
  )
}
