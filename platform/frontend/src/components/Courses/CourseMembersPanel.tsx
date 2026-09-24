import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { RefreshCw, Trash2, Users } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import useCustomToast from "@/hooks/useCustomToast"

type Member = { id: string; email: string; full_name?: string | null; enrolled_at?: string | null; completed_chapters: number; total_chapters: number }
type MembersResponse = { data: Member[]; count: number }

async function api(path: string, init?: RequestInit) {
  const response = await fetch(`/api/v1${path}`, { credentials: "include", ...init })
  const data = await response.json()
  if (!response.ok) throw new Error(data.detail || "请求失败")
  return data
}

export function CourseMembersPanel({ courseId, enrollCode }: { courseId: string; enrollCode?: string | null }) {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const members = useQuery<MembersResponse>({ queryKey: ["course-members", courseId], queryFn: () => api(`/courses/${courseId}/members`) })
  const remove = useMutation({ mutationFn: (studentId: string) => api(`/courses/${courseId}/members/${studentId}`, { method: "DELETE" }), onSuccess: () => { showSuccessToast("已移除学生"); queryClient.invalidateQueries({ queryKey: ["course-members", courseId] }) }, onError: (error) => showErrorToast(error.message) })
  const rotate = useMutation({ mutationFn: () => api(`/courses/${courseId}/enroll-code/rotate`, { method: "POST" }), onSuccess: (course) => { showSuccessToast("已更新选课码"); queryClient.invalidateQueries({ queryKey: ["courses", courseId] }); navigator.clipboard.writeText(course.enroll_code) }, onError: (error) => showErrorToast(error.message) })
  if (members.isError) return <Card><CardContent className="space-y-3 pt-6"><p role="alert" className="text-destructive">学生名单加载失败：{members.error.message}</p><Button variant="outline" onClick={() => void members.refetch()}>重新加载</Button></CardContent></Card>
  return <Card className="border-[#B00055]/15"><CardHeader className="flex-row items-center justify-between space-y-0"><CardTitle className="flex items-center gap-2 text-lg"><Users className="size-5 text-[#B00055]" />课程成员</CardTitle><Button variant="outline" size="sm" disabled={rotate.isPending} onClick={() => rotate.mutate()}><RefreshCw className="mr-1.5 size-4" />更新选课码</Button></CardHeader><CardContent className="space-y-4"><p className="text-sm text-muted-foreground">当前选课码：<code className="rounded bg-[#B00055]/5 px-2 py-1 font-semibold tracking-widest text-[#B00055]">{enrollCode || "未生成"}</code></p>{members.isLoading ? <p className="text-sm text-muted-foreground">正在加载成员…</p> : members.data?.count ? <div className="divide-y rounded-xl border">{members.data.data.map((member) => <div key={member.id} className="flex items-center gap-3 p-3"><div className="grid size-9 place-items-center rounded-full bg-[#B00055]/10 text-sm font-semibold text-[#B00055]">{(member.full_name || member.email).slice(0, 1)}</div><div className="min-w-0 flex-1"><p className="truncate text-sm font-medium">{member.full_name || "未填写姓名"}</p><p className="truncate text-xs text-muted-foreground">{member.email}</p></div><p className="text-xs text-muted-foreground">进度 {member.completed_chapters}/{member.total_chapters}</p><Button variant="ghost" size="icon-sm" aria-label="移除学生" disabled={remove.isPending} onClick={() => remove.mutate(member.id)}><Trash2 className="size-4 text-destructive" /></Button></div>)}</div> : <p className="rounded-xl border border-dashed p-5 text-center text-sm text-muted-foreground">暂时没有学生加入本课程。</p>}</CardContent></Card>
}
