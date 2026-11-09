import { useQuery } from "@tanstack/react-query"
import { createFileRoute, redirect } from "@tanstack/react-router"
import {
  Activity,
  BookOpen,
  CircleAlert,
  GraduationCap,
  LayoutDashboard,
  MessageSquare,
  RefreshCw,
} from "lucide-react"
import { useMemo, useState } from "react"
import { UsersService } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { usePlatformStatus } from "@/hooks/usePlatformStatus"
import { cn } from "@/lib/utils"

type ServiceRow = { name: string; ok: boolean; detail: string }

type Overview = {
  users: { total: number; teachers: number; students: number }
  online: { students: number; teachers: number; windowMinutes: number }
  courses: number
  enrollments: number
  chat: {
    total: number
    last24h: number
    activeStudents24h: number
    trend: Array<{ date: string; count: number }>
  } | null
  services: ServiceRow[]
  pending: Array<{
    kind: string
    severity: string
    text: string
    count: number | null
  }>
}

type CourseHealthRow = {
  id: string
  title: string
  owner: string
  students: number
  published: boolean | null
  publicationVersion: number | null
  sessionCount: number | null
  lastActiveAt: string | null
  activeStudents7d: number | null
  risk: string
}

type StudentActivityRow = {
  id: string
  name: string
  email: string
  courses: number
  sessionCount: number
  lastActiveAt: string | null
  risk: string
}

type ChatSessionRow = {
  sessionKey: string
  courseId: string
  course: string
  student: string
  studentId: string
  lesson: string
  startedAt: string | null
  lastActiveAt: string | null
  ended: boolean
  messageCount: number
}

type ChatMessageRow = {
  seq: number
  role: string
  phase: string | null
  content: string
  createdAt: string | null
}

async function api<T>(path: string): Promise<T> {
  const response = await fetch(`/api/v1${path}`, { credentials: "include" })
  if (!response.ok) {
    // error bodies may be plain text (e.g. "Internal Server Error"), not JSON
    const text = await response.text()
    let detail = text
    try {
      detail = JSON.parse(text).detail ?? text
    } catch {
      // keep raw text
    }
    throw new Error(detail || `请求失败(${response.status})`)
  }
  return response.json()
}

function formatTime(value: string | null | undefined): string {
  if (!value) return "—"
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString()
}

function relativeTime(value: string | null | undefined): string {
  if (!value) return "—"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return "—"
  const minutes = Math.round((Date.now() - date.getTime()) / 60000)
  if (minutes < 1) return "刚刚"
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.round(hours / 24)
  if (days < 30) return `${days} 天前`
  return date.toLocaleDateString()
}

export const Route = createFileRoute("/_layout/console")({
  component: DevConsole,
  beforeLoad: async () => {
    const { data: user } = await UsersService.readUserMe()
    if (!user.is_superuser && user.role !== "observer") {
      throw redirect({
        to: "/",
      })
    }
  },
  head: () => ({
    meta: [
      {
        title: "开发运维中心 - AI 教育平台",
      },
    ],
  }),
})

type Section =
  | { kind: "overview" }
  | { kind: "course-health" }
  | { kind: "students" }
  | { kind: "chat" }
  | { kind: "services" }

/** 语义状态:绿=正常,黄=待关注,红=需处理,灰=无数据。 */
function StatusBadge({ label }: { label: string }) {
  const ok = ["正常", "已发布", "在线"]
  const warn = [
    "7天无活动",
    "无会话",
    "已选课未发布",
    "7天未活跃",
    "从未学习",
    "待关注",
  ]
  const bad = ["需处理"]
  const dot = ok.includes(label)
    ? "bg-emerald-500"
    : bad.includes(label)
      ? "bg-red-500"
      : warn.includes(label)
        ? "bg-amber-500"
        : "bg-gray-400"
  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <span className={cn("inline-block size-2 rounded-full", dot)} />
      {label}
    </span>
  )
}

function ServiceDots({ services }: { services: ServiceRow[] | undefined }) {
  return (
    <div className="flex items-center gap-4 text-sm">
      <span className="flex items-center gap-1.5">
        <span className="inline-block size-2 rounded-full bg-emerald-500" />
        平台
      </span>
      {(services ?? []).map((service) => (
        <span key={service.name} className="flex items-center gap-1.5">
          <span
            className={cn(
              "inline-block size-2 rounded-full",
              service.ok ? "bg-emerald-500" : "bg-red-500",
            )}
          />
          {service.name}
        </span>
      ))}
    </div>
  )
}

function StatTile({
  label,
  value,
  hint,
}: {
  label: string
  value: string | number
  hint?: string
}) {
  return (
    <Card className="py-3">
      <CardContent className="space-y-0.5 px-4">
        <p className="text-xs font-medium text-muted-foreground">{label}</p>
        <p className="text-xl font-semibold tracking-tight">{value}</p>
        {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      </CardContent>
    </Card>
  )
}

/** 单系列日柱状图:单色、细柱、悬停数值、无图例。 */
function TrendChart({
  trend,
}: {
  trend: Array<{ date: string; count: number }>
}) {
  const max = Math.max(1, ...trend.map((point) => point.count))
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium">近 7 天会话数</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex h-24 items-end gap-2">
          {trend.map((point) => (
            <div
              key={point.date}
              className="group flex flex-1 flex-col items-center justify-end gap-1"
              title={`${point.date}:${point.count} 个会话`}
            >
              <span className="text-[10px] text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100">
                {point.count}
              </span>
              <div
                className="w-full rounded-t-sm bg-[#3987e5] transition-colors group-hover:bg-[#2a78d6]"
                style={{ height: `${Math.max(2, (point.count / max) * 84)}px` }}
              />
            </div>
          ))}
        </div>
        <div className="mt-1 flex gap-2 text-[10px] text-muted-foreground">
          {trend.map((point) => (
            <span key={point.date} className="flex-1 text-center">
              {point.date.slice(5)}
            </span>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}

function ViewError({ label, error }: { label: string; error: unknown }) {
  return (
    <div className="space-y-1">
      <p className="flex items-center gap-2 text-sm text-destructive">
        <CircleAlert className="size-4" />
        {label}失败:{String(error)}
      </p>
      <p className="text-xs text-muted-foreground">
        请确认相关服务已启动;若持续失败,查看平台服务日志。
      </p>
    </div>
  )
}

function EmptyHint({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
      {children}
    </div>
  )
}

function PendingList({
  pending,
  onNavigate,
}: {
  pending: Overview["pending"]
  onNavigate: (section: Section) => void
}) {
  if (pending.length === 0) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium">需要处理</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="flex items-center gap-2 text-sm">
            <span className="inline-block size-2 rounded-full bg-emerald-500" />
            当前没有需要处理的事项
          </p>
        </CardContent>
      </Card>
    )
  }
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium">需要处理</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {pending.map((item, index) => (
          <button
            key={`${item.kind}-${index}`}
            type="button"
            className="flex w-full items-center justify-between rounded-md border px-3 py-2 text-left text-sm hover:bg-accent/50"
            onClick={() =>
              onNavigate(
                item.kind === "service"
                  ? { kind: "services" }
                  : item.kind === "publication"
                    ? { kind: "course-health" }
                    : { kind: "students" },
              )
            }
          >
            <span className="flex items-center gap-2">
              <span
                className={cn(
                  "inline-block size-2 rounded-full",
                  item.severity === "critical" ? "bg-red-500" : "bg-amber-500",
                )}
              />
              {item.text}
            </span>
            <span className="text-xs text-muted-foreground">
              {item.kind === "service"
                ? "查看服务 →"
                : item.kind === "publication"
                  ? "查看课程 →"
                  : "查看学生 →"}
            </span>
          </button>
        ))}
      </CardContent>
    </Card>
  )
}

function OverviewView({
  onNavigate,
}: {
  onNavigate: (section: Section) => void
}) {
  const { data, error, isLoading } = useQuery({
    queryKey: ["dev-console-overview"],
    queryFn: () => api<Overview>("/dev-console/overview"),
  })
  if (isLoading) return <p className="text-muted-foreground">加载中…</p>
  if (error || !data)
    return <ViewError label="概览加载" error={error ?? "无数据"} />
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <StatTile
          label="正在线"
          value={data.online.students + data.online.teachers}
          hint={`学生 ${data.online.students} · 教师 ${data.online.teachers} · ${data.online.windowMinutes} 分钟内有活动`}
        />
        <StatTile
          label="新会话(24h)"
          value={data.chat ? data.chat.last24h : "—"}
        />
        <StatTile
          label="学生会话总量"
          value={data.chat ? data.chat.total : "—"}
        />
        <StatTile
          label="课程"
          value={data.courses}
          hint={`选课 ${data.enrollments}`}
        />
        <StatTile
          label="用户"
          value={data.users.total}
          hint={`教师 ${data.users.teachers} · 学生 ${data.users.students}`}
        />
      </div>
      <PendingList pending={data.pending} onNavigate={onNavigate} />
      {data.chat ? (
        <TrendChart trend={data.chat.trend} />
      ) : (
        <EmptyHint>
          近 7 天趋势暂缺:学生服务当前不可用,无法统计会话数据。
        </EmptyHint>
      )}
    </div>
  )
}

type SessionFilters = {
  courseId?: string
  studentId?: string
  q?: string
  lesson?: string
  ended?: string
  activeDays?: string
}

function useChatSessions(filters: SessionFilters = {}) {
  const params = new URLSearchParams()
  if (filters.courseId) params.set("course_id", filters.courseId)
  if (filters.studentId) params.set("student_id", filters.studentId)
  if (filters.q) params.set("q", filters.q)
  if (filters.lesson) params.set("lesson", filters.lesson)
  if (filters.ended) params.set("ended", filters.ended)
  if (filters.activeDays) params.set("active_days", filters.activeDays)
  return useQuery({
    queryKey: ["dev-console-chat-sessions", params.toString()],
    queryFn: () =>
      api<{ sessions: ChatSessionRow[]; unavailableCourses: string[] }>(
        `/dev-console/chat-sessions?${params.toString()}`,
      ),
  })
}

function SessionTable({
  sessions,
  onSelect,
  showCourse,
}: {
  sessions: ChatSessionRow[]
  onSelect: (session: ChatSessionRow) => void
  showCourse?: boolean
}) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>学生</TableHead>
          {showCourse && <TableHead>课程</TableHead>}
          <TableHead>课时</TableHead>
          <TableHead>消息数</TableHead>
          <TableHead>状态</TableHead>
          <TableHead>最近活跃</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {sessions.map((row) => (
          <TableRow
            key={`${row.courseId}-${row.sessionKey}`}
            className="cursor-pointer"
            onClick={() => onSelect(row)}
          >
            <TableCell>{row.student}</TableCell>
            {showCourse && <TableCell>{row.course}</TableCell>}
            <TableCell>{row.lesson}</TableCell>
            <TableCell>{row.messageCount}</TableCell>
            <TableCell>
              <Badge variant={row.ended ? "secondary" : "default"}>
                {row.ended ? "已结束" : "进行中"}
              </Badge>
            </TableCell>
            <TableCell className="text-muted-foreground">
              {relativeTime(row.lastActiveAt)}
            </TableCell>
          </TableRow>
        ))}
        {sessions.length === 0 && (
          <TableRow>
            <TableCell
              colSpan={showCourse ? 6 : 5}
              className="text-muted-foreground"
            >
              没有会话记录
            </TableCell>
          </TableRow>
        )}
      </TableBody>
    </Table>
  )
}

function UnavailableNote({ courses }: { courses: string[] }) {
  if (courses.length === 0) return null
  return (
    <p className="flex items-center gap-2 text-sm text-amber-600">
      <CircleAlert className="size-4" />
      以下课程的聊天数据未能读取:{courses.join("、")}
    </p>
  )
}

function TranscriptPanel({
  session,
  onBack,
}: {
  session: ChatSessionRow
  onBack: () => void
}) {
  const { data, error, isLoading } = useQuery({
    queryKey: ["dev-console-messages", session.courseId, session.sessionKey],
    queryFn: () =>
      api<ChatMessageRow[]>(
        `/dev-console/courses/${session.courseId}/chat-sessions/${encodeURIComponent(session.sessionKey)}/messages`,
      ),
  })
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">
            {session.student} · {session.lesson}
          </h2>
          <p className="text-sm text-muted-foreground">
            {session.course} · {session.messageCount} 条消息 · 最近活跃{" "}
            {formatTime(session.lastActiveAt)}
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={onBack}>
          返回列表
        </Button>
      </div>
      {isLoading && <p className="text-muted-foreground">加载中…</p>}
      {error && (
        <p className="text-destructive">
          聊天记录不可用:{String(error)}
          。可能原因:学生服务未启动,或该会话数据尚未同步。
        </p>
      )}
      <div className="space-y-3">
        {data?.map((message) => (
          <div
            key={message.seq}
            className={`flex flex-col ${message.role === "student" ? "items-start" : "items-end"}`}
          >
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <span>{message.role === "student" ? "学生" : "助教"}</span>
              {message.phase && (
                <Badge variant="outline">{message.phase}</Badge>
              )}
              <span>{formatTime(message.createdAt)}</span>
            </div>
            <div
              className={cn(
                "mt-1 max-w-[70%] rounded-lg px-3 py-2 text-sm whitespace-pre-wrap",
                message.role === "student"
                  ? "bg-muted"
                  : "bg-primary text-primary-foreground",
              )}
            >
              {message.content}
            </div>
          </div>
        ))}
        {data?.length === 0 && (
          <EmptyHint>
            这个会话没有消息记录:该学生可能进入了课堂但尚未发言。
          </EmptyHint>
        )}
      </div>
    </div>
  )
}

const PAGE_SIZE = 50

/** 列头排序按钮:点击切换升/降序,第三态为未排序。 */
function SortableTh({
  label,
  sortKey,
  active,
  dir,
  onToggle,
}: {
  label: string
  sortKey: string
  active: string | null
  dir: "asc" | "desc"
  onToggle: (key: string) => void
}) {
  return (
    <TableHead>
      <button
        type="button"
        className="flex items-center gap-1 hover:text-foreground"
        onClick={() => onToggle(sortKey)}
      >
        {label}
        <span className="text-[10px] text-muted-foreground">
          {active === sortKey ? (dir === "asc" ? "▲" : "▼") : "↕"}
        </span>
      </button>
    </TableHead>
  )
}

/** 排序 + 分页(null 值永远排最后)。 */
function useSortedPaged<T>(
  rows: T[],
  extractors: Record<string, (row: T) => number | string | null>,
) {
  const [sortKey, setSortKey] = useState<string | null>(null)
  const [dir, setDir] = useState<"asc" | "desc">("asc")
  const [page, setPage] = useState(0)
  const sorted = useMemo(() => {
    if (!sortKey) return rows
    const get = extractors[sortKey]
    const result = [...rows].sort((a, b) => {
      const av = get(a)
      const bv = get(b)
      if (av === null) return 1
      if (bv === null) return -1
      if (typeof av === "number" && typeof bv === "number") return av - bv
      return String(av).localeCompare(String(bv), "zh")
    })
    return dir === "desc" ? result.reverse() : result
  }, [rows, sortKey, dir])
  const pageCount = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE))
  const safePage = Math.min(page, pageCount - 1)
  const paged = sorted.slice(safePage * PAGE_SIZE, (safePage + 1) * PAGE_SIZE)
  const toggle = (key: string) => {
    if (sortKey === key) {
      setDir(dir === "asc" ? "desc" : "asc")
    } else {
      setSortKey(key)
      setDir("asc")
    }
    setPage(0)
  }
  const totalPages = sorted.length > PAGE_SIZE ? pageCount : 0
  return {
    paged,
    total: sorted.length,
    sortKey,
    dir,
    toggle,
    safePage,
    totalPages,
    setPage,
  }
}

function TablePager({
  page,
  totalPages,
  setPage,
}: {
  page: number
  totalPages: number
  setPage: (page: number) => void
}) {
  if (totalPages === 0) return null
  return (
    <div className="flex items-center justify-end gap-2 text-xs text-muted-foreground">
      <Button
        variant="outline"
        size="sm"
        disabled={page === 0}
        onClick={() => setPage(page - 1)}
      >
        上一页
      </Button>
      <span>
        第 {page + 1} / {totalPages} 页
      </span>
      <Button
        variant="outline"
        size="sm"
        disabled={page >= totalPages - 1}
        onClick={() => setPage(page + 1)}
      >
        下一页
      </Button>
    </div>
  )
}

const COURSE_RISKS = [
  "正常",
  "7天无活动",
  "无会话",
  "已选课未发布",
  "无学生",
  "状态未知",
  "数据不可用",
]
const STUDENT_RISKS = [
  "在线",
  "正常",
  "7天未活跃",
  "从未学习",
  "无选课",
  "数据不可用",
]

function CourseHealthView({
  onSelectCourse,
}: {
  onSelectCourse: (course: CourseHealthRow) => void
}) {
  const [query, setQuery] = useState("")
  const [risk, setRisk] = useState("all")
  const [published, setPublished] = useState("all")
  const { data, error, isLoading } = useQuery({
    queryKey: ["dev-console-course-health"],
    queryFn: () => api<CourseHealthRow[]>("/dev-console/course-health"),
  })
  const filtered = useMemo(() => {
    let rows = data ?? []
    const needle = query.trim().toLowerCase()
    if (needle) {
      rows = rows.filter(
        (row) =>
          row.title.toLowerCase().includes(needle) ||
          (row.owner ?? "").toLowerCase().includes(needle),
      )
    }
    if (risk !== "all") rows = rows.filter((row) => row.risk === risk)
    if (published !== "all") {
      rows = rows.filter(
        (row) =>
          (published === "yes" && row.published === true) ||
          (published === "no" && row.published === false) ||
          (published === "unknown" && row.published === null),
      )
    }
    return rows
  }, [data, query, risk, published])
  const table = useSortedPaged<CourseHealthRow>(filtered, {
    title: (row) => row.title,
    owner: (row) => row.owner ?? "",
    students: (row) => row.students,
    published: (row) =>
      row.published === null ? "状态未知" : row.published ? "已发布" : "未发布",
    sessionCount: (row) => row.sessionCount,
    activeStudents7d: (row) => row.activeStudents7d,
    lastActiveAt: (row) => row.lastActiveAt,
    risk: (row) => row.risk,
  })
  if (isLoading) return <p className="text-muted-foreground">加载中…</p>
  if (error) return <ViewError label="课程健康加载" error={error} />
  const t = table
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="按课程名 / 教师搜索…"
          className="w-56"
        />
        <Select value={risk} onValueChange={setRisk}>
          <SelectTrigger className="w-36">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部风险</SelectItem>
            {COURSE_RISKS.map((value) => (
              <SelectItem key={value} value={value}>
                {value}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={published} onValueChange={setPublished}>
          <SelectTrigger className="w-32">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">发布不限</SelectItem>
            <SelectItem value="yes">已发布</SelectItem>
            <SelectItem value="no">未发布</SelectItem>
            <SelectItem value="unknown">状态未知</SelectItem>
          </SelectContent>
        </Select>
        <span className="ml-auto text-xs text-muted-foreground">
          {t.total} 门课程
        </span>
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <SortableTh
              label="课程"
              sortKey="title"
              active={t.sortKey}
              dir={t.dir}
              onToggle={t.toggle}
            />
            <SortableTh
              label="教师"
              sortKey="owner"
              active={t.sortKey}
              dir={t.dir}
              onToggle={t.toggle}
            />
            <SortableTh
              label="学生数"
              sortKey="students"
              active={t.sortKey}
              dir={t.dir}
              onToggle={t.toggle}
            />
            <SortableTh
              label="发布状态"
              sortKey="published"
              active={t.sortKey}
              dir={t.dir}
              onToggle={t.toggle}
            />
            <SortableTh
              label="会话数"
              sortKey="sessionCount"
              active={t.sortKey}
              dir={t.dir}
              onToggle={t.toggle}
            />
            <SortableTh
              label="7 天活跃"
              sortKey="activeStudents7d"
              active={t.sortKey}
              dir={t.dir}
              onToggle={t.toggle}
            />
            <SortableTh
              label="最近活动"
              sortKey="lastActiveAt"
              active={t.sortKey}
              dir={t.dir}
              onToggle={t.toggle}
            />
            <SortableTh
              label="风险"
              sortKey="risk"
              active={t.sortKey}
              dir={t.dir}
              onToggle={t.toggle}
            />
          </TableRow>
        </TableHeader>
        <TableBody>
          {t.paged.map((row) => (
            <TableRow
              key={row.id}
              className="cursor-pointer"
              onClick={() => onSelectCourse(row)}
            >
              <TableCell>{row.title}</TableCell>
              <TableCell>{row.owner}</TableCell>
              <TableCell>{row.students}</TableCell>
              <TableCell>
                <StatusBadge
                  label={
                    row.published === null
                      ? "状态未知"
                      : row.published
                        ? "已发布"
                        : "已选课未发布"
                  }
                />
              </TableCell>
              <TableCell>{row.sessionCount ?? "—"}</TableCell>
              <TableCell>{row.activeStudents7d ?? "—"}</TableCell>
              <TableCell className="text-muted-foreground">
                {relativeTime(row.lastActiveAt)}
              </TableCell>
              <TableCell>
                <StatusBadge label={row.risk} />
              </TableCell>
            </TableRow>
          ))}
          {t.paged.length === 0 && (
            <TableRow>
              <TableCell colSpan={8} className="text-muted-foreground">
                没有符合条件的课程
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
      <TablePager
        page={t.safePage}
        totalPages={t.totalPages}
        setPage={t.setPage}
      />
    </div>
  )
}

function StudentActivityView({
  onSelectStudent,
}: {
  onSelectStudent: (student: StudentActivityRow) => void
}) {
  const [query, setQuery] = useState("")
  const [risk, setRisk] = useState("all")
  const { data, error, isLoading } = useQuery({
    queryKey: ["dev-console-student-activity"],
    queryFn: () => api<StudentActivityRow[]>("/dev-console/student-activity"),
  })
  const filtered = useMemo(() => {
    let rows = data ?? []
    const needle = query.trim().toLowerCase()
    if (needle) {
      rows = rows.filter(
        (row) =>
          row.name.toLowerCase().includes(needle) ||
          (row.email ?? "").toLowerCase().includes(needle),
      )
    }
    if (risk !== "all") rows = rows.filter((row) => row.risk === risk)
    return rows
  }, [data, query, risk])
  const t = useSortedPaged<StudentActivityRow>(filtered, {
    name: (row) => row.name,
    courses: (row) => row.courses,
    sessionCount: (row) => row.sessionCount,
    lastActiveAt: (row) => row.lastActiveAt,
    risk: (row) => row.risk,
  })
  if (isLoading) return <p className="text-muted-foreground">加载中…</p>
  if (error) return <ViewError label="学生活跃度加载" error={error} />
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="按姓名 / 邮箱搜索…"
          className="w-56"
        />
        <Select value={risk} onValueChange={setRisk}>
          <SelectTrigger className="w-36">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部状态</SelectItem>
            {STUDENT_RISKS.map((value) => (
              <SelectItem key={value} value={value}>
                {value}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <span className="ml-auto text-xs text-muted-foreground">
          {t.total} 名学生
        </span>
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <SortableTh
              label="姓名"
              sortKey="name"
              active={t.sortKey}
              dir={t.dir}
              onToggle={t.toggle}
            />
            <SortableTh
              label="选课数"
              sortKey="courses"
              active={t.sortKey}
              dir={t.dir}
              onToggle={t.toggle}
            />
            <SortableTh
              label="会话数"
              sortKey="sessionCount"
              active={t.sortKey}
              dir={t.dir}
              onToggle={t.toggle}
            />
            <SortableTh
              label="最近活跃"
              sortKey="lastActiveAt"
              active={t.sortKey}
              dir={t.dir}
              onToggle={t.toggle}
            />
            <SortableTh
              label="状态"
              sortKey="risk"
              active={t.sortKey}
              dir={t.dir}
              onToggle={t.toggle}
            />
          </TableRow>
        </TableHeader>
        <TableBody>
          {t.paged.map((row) => (
            <TableRow
              key={row.id}
              className="cursor-pointer"
              onClick={() => onSelectStudent(row)}
            >
              <TableCell>{row.name}</TableCell>
              <TableCell>{row.courses}</TableCell>
              <TableCell>{row.sessionCount}</TableCell>
              <TableCell className="text-muted-foreground">
                {relativeTime(row.lastActiveAt)}
              </TableCell>
              <TableCell>
                <StatusBadge label={row.risk} />
              </TableCell>
            </TableRow>
          ))}
          {t.paged.length === 0 && (
            <TableRow>
              <TableCell colSpan={5} className="text-muted-foreground">
                没有符合条件的学生
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
      <TablePager
        page={t.safePage}
        totalPages={t.totalPages}
        setPage={t.setPage}
      />
    </div>
  )
}

/** 对话排查:每个字段独立筛选(课程/学生/课时/状态/活跃时间),各查各的。 */
function ChatDiagnosisView({
  onSelectSession,
}: {
  onSelectSession: (session: ChatSessionRow) => void
}) {
  const [courseId, setCourseId] = useState("all")
  const [studentId, setStudentId] = useState("all")
  const [lessonDraft, setLessonDraft] = useState("")
  const [lesson, setLesson] = useState("")
  const [ended, setEnded] = useState("all")
  const [activeDays, setActiveDays] = useState("all")
  const courses = useQuery({
    queryKey: ["dev-console-courses"],
    queryFn: () =>
      api<Array<{ id: string; title: string }>>("/dev-console/courses"),
  })
  const students = useQuery({
    queryKey: ["dev-console-students"],
    queryFn: () =>
      api<Array<{ id: string; name: string }>>("/dev-console/students"),
  })
  const { data, error, isLoading, isFetching } = useChatSessions({
    courseId: courseId === "all" ? undefined : courseId,
    studentId: studentId === "all" ? undefined : studentId,
    lesson: lesson || undefined,
    ended: ended === "all" ? undefined : ended,
    activeDays: activeDays === "all" ? undefined : activeDays,
  })
  const hasFilters =
    courseId !== "all" ||
    studentId !== "all" ||
    lesson !== "" ||
    ended !== "all" ||
    activeDays !== "all"
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Select value={courseId} onValueChange={setCourseId}>
          <SelectTrigger className="w-44">
            <SelectValue placeholder="全部课程" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部课程</SelectItem>
            {courses.data?.map((course) => (
              <SelectItem key={course.id} value={course.id}>
                {course.title}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={studentId} onValueChange={setStudentId}>
          <SelectTrigger className="w-36">
            <SelectValue placeholder="全部学生" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部学生</SelectItem>
            {students.data?.map((student) => (
              <SelectItem key={student.id} value={student.id}>
                {student.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Input
          value={lessonDraft}
          onChange={(event) => setLessonDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") setLesson(lessonDraft.trim())
          }}
          onBlur={() => setLesson(lessonDraft.trim())}
          placeholder="课时名称包含…"
          className="w-40"
        />
        <Select value={ended} onValueChange={setEnded}>
          <SelectTrigger className="w-28">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部状态</SelectItem>
            <SelectItem value="false">进行中</SelectItem>
            <SelectItem value="true">已结束</SelectItem>
          </SelectContent>
        </Select>
        <Select value={activeDays} onValueChange={setActiveDays}>
          <SelectTrigger className="w-32">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">活跃时间不限</SelectItem>
            <SelectItem value="1">24 小时内</SelectItem>
            <SelectItem value="7">7 天内</SelectItem>
            <SelectItem value="30">30 天内</SelectItem>
          </SelectContent>
        </Select>
        {hasFilters && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setCourseId("all")
              setStudentId("all")
              setLessonDraft("")
              setLesson("")
              setEnded("all")
              setActiveDays("all")
            }}
          >
            清除筛选
          </Button>
        )}
        {isFetching && (
          <RefreshCw className="size-3.5 animate-spin text-muted-foreground" />
        )}
      </div>
      {isLoading && <p className="text-muted-foreground">加载中…</p>}
      {error && <ViewError label="会话加载" error={error} />}
      {data && (
        <>
          <UnavailableNote courses={data.unavailableCourses} />
          {data.sessions.length === 0 ? (
            <EmptyHint>
              当前筛选范围内未找到会话。可能原因:该学生尚未进入学习页面发起对话;或学生服务未能同步会话数据
              {data.unavailableCourses.length > 0
                ? `(部分课程读取失败:${data.unavailableCourses.join("、")})`
                : ""}
              ;或筛选条件过严(可点击"清除筛选"重试)。
            </EmptyHint>
          ) : (
            <SessionTable
              sessions={data.sessions}
              onSelect={onSelectSession}
              showCourse
            />
          )}
        </>
      )}
    </div>
  )
}

function ServicesView() {
  const { data, error, isLoading } = useQuery({
    queryKey: ["dev-console-overview"],
    queryFn: () => api<Overview>("/dev-console/overview"),
    refetchInterval: 30_000,
  })
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        每 30 秒自动探测一次;错误率、响应耗时等指标需要日志基建(后续版本)。
      </p>
      {isLoading && <p className="text-muted-foreground">加载中…</p>}
      {error && <ViewError label="服务状态加载" error={error} />}
      {data && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>服务</TableHead>
              <TableHead>状态</TableHead>
              <TableHead>最近检查</TableHead>
              <TableHead>说明</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow>
              <TableCell>平台(platform)</TableCell>
              <TableCell>
                <StatusBadge label="正常" />
              </TableCell>
              <TableCell className="text-muted-foreground">
                刚刚(本页)
              </TableCell>
              <TableCell className="text-muted-foreground">—</TableCell>
            </TableRow>
            {data.services.map((service) => (
              <TableRow key={service.name}>
                <TableCell>{service.name}</TableCell>
                <TableCell>
                  <StatusBadge label={service.ok ? "正常" : "需处理"} />
                </TableCell>
                <TableCell className="text-muted-foreground">
                  刚刚(30s 自动刷新)
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {service.detail || "—"}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  )
}

function CourseDetailView({
  course,
  onSelectSession,
}: {
  course: CourseHealthRow
  onSelectSession: (session: ChatSessionRow) => void
}) {
  const { data, error, isLoading } = useChatSessions({ courseId: course.id })
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">{course.title}</h2>
          <p className="text-sm text-muted-foreground">
            教师 {course.owner} · {course.students} 名学生 · 发布版本{" "}
            {course.publicationVersion ?? "未发布"}
          </p>
        </div>
        <StatusBadge label={course.risk} />
      </div>
      <p className="text-sm text-muted-foreground">
        会话 {course.sessionCount ?? "—"} 个 · 7 天活跃学生{" "}
        {course.activeStudents7d ?? "—"} 人 · 最近活动{" "}
        {relativeTime(course.lastActiveAt)}
      </p>
      {isLoading && <p className="text-muted-foreground">加载中…</p>}
      {error && <ViewError label="会话加载" error={error} />}
      {data && (
        <>
          <UnavailableNote courses={data.unavailableCourses} />
          {data.sessions.length === 0 ? (
            <EmptyHint>
              该课程还没有会话:可能是学生尚未进入学习页面,或课程内容尚未发布导致学生无法开始学习。
            </EmptyHint>
          ) : (
            <SessionTable sessions={data.sessions} onSelect={onSelectSession} />
          )}
        </>
      )}
    </div>
  )
}

function StudentDetailView({
  student,
  onSelectSession,
}: {
  student: StudentActivityRow
  onSelectSession: (session: ChatSessionRow) => void
}) {
  const { data, error, isLoading } = useChatSessions({ studentId: student.id })
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">{student.name}</h2>
          <p className="text-sm text-muted-foreground">
            选课 {student.courses} 门 · 会话 {student.sessionCount} 个 ·
            最近活跃 {relativeTime(student.lastActiveAt)}
          </p>
        </div>
        <StatusBadge label={student.risk} />
      </div>
      {isLoading && <p className="text-muted-foreground">加载中…</p>}
      {error && <ViewError label="会话加载" error={error} />}
      {data && (
        <>
          <UnavailableNote courses={data.unavailableCourses} />
          {data.sessions.length === 0 ? (
            <EmptyHint>
              该学生还没有会话:可能尚未进入学习页面,或所选课程内容未发布、学生
              Agent 未同步数据。
            </EmptyHint>
          ) : (
            <SessionTable
              sessions={data.sessions}
              onSelect={onSelectSession}
              showCourse
            />
          )}
        </>
      )}
    </div>
  )
}

const NAV_GROUPS: Array<{
  label: string
  items: Array<{ section: Section; label: string; icon: typeof BookOpen }>
}> = [
  {
    label: "",
    items: [
      { section: { kind: "overview" }, label: "概览", icon: LayoutDashboard },
    ],
  },
  {
    label: "业务诊断",
    items: [
      { section: { kind: "course-health" }, label: "课程健康", icon: BookOpen },
      { section: { kind: "students" }, label: "学生活跃", icon: GraduationCap },
      { section: { kind: "chat" }, label: "对话排查", icon: MessageSquare },
    ],
  },
  {
    label: "系统观测",
    items: [
      { section: { kind: "services" }, label: "服务状态", icon: Activity },
    ],
  },
]

/** 左侧导航:按开发动作组织(概览 / 业务诊断 / 系统观测)。 */
function ConsoleNav({
  activeKind,
  onNavigate,
}: {
  /** nav kind to highlight; detail views map back to their section */
  activeKind: Section["kind"]
  onNavigate: (section: Section) => void
}) {
  const overview = useQuery({
    queryKey: ["dev-console-overview"],
    queryFn: () => api<Overview>("/dev-console/overview"),
    refetchInterval: 30_000,
  })
  const criticalCount = (overview.data?.pending ?? []).filter(
    (item) => item.severity === "critical",
  ).length
  return (
    <nav className="flex w-56 shrink-0 flex-col gap-1 overflow-y-auto border-r p-2">
      {NAV_GROUPS.map((group, groupIndex) => (
        <div key={group.label || `group-${groupIndex}`}>
          {group.label && (
            <p className="mt-3 px-2 text-xs font-medium text-muted-foreground">
              {group.label}
            </p>
          )}
          {group.items.map((item) => {
            const active = activeKind === item.section.kind
            return (
              <button
                key={item.section.kind}
                type="button"
                onClick={() => onNavigate(item.section)}
                className={cn(
                  "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm",
                  active ? "bg-accent font-medium" : "hover:bg-accent/50",
                )}
              >
                <item.icon className="size-4" />
                {item.label}
                {item.section.kind === "services" && criticalCount > 0 && (
                  <span className="ml-auto inline-flex size-4 items-center justify-center rounded-full bg-red-500 text-[10px] font-medium text-white">
                    {criticalCount}
                  </span>
                )}
              </button>
            )
          })}
        </div>
      ))}
    </nav>
  )
}

/**
 * 内部开发运维中心(只读):按开发问题组织 —— 系统正常吗、哪里需要处理、
 * 具体排障。observer/superuser 专用,学生/教师不可见。
 */
function DevConsole() {
  const [section, setSection] = useState<Section>({ kind: "overview" })
  const [course, setCourse] = useState<CourseHealthRow | null>(null)
  const [student, setStudent] = useState<StudentActivityRow | null>(null)
  const [session, setSession] = useState<ChatSessionRow | null>(null)
  const status = usePlatformStatus()

  const navigate = (next: Section) => {
    setCourse(null)
    setStudent(null)
    setSession(null)
    setSection(next)
  }

  let body: React.ReactNode
  if (session) {
    body = <TranscriptPanel session={session} onBack={() => setSession(null)} />
  } else if (course) {
    body = <CourseDetailView course={course} onSelectSession={setSession} />
  } else if (student) {
    body = <StudentDetailView student={student} onSelectSession={setSession} />
  } else {
    body = (() => {
      switch (section.kind) {
        case "overview":
          return <OverviewView onNavigate={navigate} />
        case "course-health":
          return <CourseHealthView onSelectCourse={setCourse} />
        case "students":
          return <StudentActivityView onSelectStudent={setStudent} />
        case "chat":
          return <ChatDiagnosisView onSelectSession={setSession} />
        case "services":
          return <ServicesView />
      }
    })()
  }

  return (
    <div className="flex h-[calc(100vh-4rem)] flex-col">
      <div className="flex items-center justify-between border-b px-6 py-3">
        <div className="flex items-center gap-2">
          <h1 className="text-base font-semibold tracking-tight">
            开发运维中心
          </h1>
          <span className="text-xs text-muted-foreground">
            只读 · 仅内部观察角色可见
          </span>
        </div>
        <div className="flex items-center gap-3">
          <RefreshCw
            className={cn(
              "size-3.5 cursor-pointer text-muted-foreground",
              status.isFetching && "animate-spin",
            )}
          />
          <ServiceDots
            services={
              status.data
                ? [
                    {
                      name: "教师",
                      ok: status.data.teacherReady === true,
                      detail: "",
                    },
                    {
                      name: "学生",
                      ok: status.data.studentAgentReady === true,
                      detail: "",
                    },
                  ]
                : undefined
            }
          />
        </div>
      </div>
      <div className="flex min-h-0 flex-1">
        <ConsoleNav
          activeKind={
            course ? "course-health" : student ? "students" : section.kind
          }
          onNavigate={navigate}
        />
        <main className="min-w-0 flex-1 overflow-y-auto p-6">
          <div className="max-w-5xl">{body}</div>
        </main>
      </div>
    </div>
  )
}
