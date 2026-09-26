import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Eye, EyeOff, Loader2, SlidersHorizontal } from "lucide-react"
import { useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import useAuth from "@/hooks/useAuth"
import { cn } from "@/lib/utils"

/**
 * 模型配置入口对话框。
 * - 教师/管理员：内嵌教师端的系统模型配置面板（/settings?embed=1），
 *   面板里点 X 会 postMessage 通知这里一起关闭。
 * - 学生：沿用同一套面板样式，但只保留学生实际需要的「语言模型」
 *   （个人 BYOK 配置，接口仍是 /users/me/model-config）。
 */
export function ModelConfigDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { user: currentUser } = useAuth()
  const isStudent = currentUser?.role === "student"

  useEffect(() => {
    if (!open) return
    function onMessage(e: MessageEvent) {
      if (e.data?.source === "teacher-settings" && e.data?.event === "closed") {
        onOpenChange(false)
      }
    }
    window.addEventListener("message", onMessage)
    return () => window.removeEventListener("message", onMessage)
  }, [open, onOpenChange])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {isStudent ? (
        <StudentModelPanel open={open} />
      ) : (
        <DialogContent
          className="h-[96vh] w-[98vw] max-w-none sm:max-w-none overflow-hidden p-0 gap-0"
          showCloseButton={false}
        >
          <DialogTitle className="sr-only">模型配置</DialogTitle>
          <iframe
            src="/settings?embed=1"
            title="模型配置"
            className="h-full w-full border-0"
            onLoad={(e) => enlargeSettingsPanel(e.currentTarget)}
          />
        </DialogContent>
      )}
    </Dialog>
  )
}

/**
 * 教师端设置面板自带 max-w-3/4 / h-[85vh]，在大对话框里四周留白很大。
 * 平台与教师端同源，这里在 iframe 加载后把面板撑满对话框（免重建教师镜像）。
 */
function enlargeSettingsPanel(iframe: HTMLIFrameElement) {
  const doc = iframe.contentDocument
  if (!doc) return
  const apply = () => {
    const dlg = doc.querySelector('[role="dialog"]') as HTMLElement | null
    if (!dlg) return false
    dlg.style.setProperty("width", "100%", "important")
    dlg.style.setProperty("max-width", "none", "important")
    dlg.style.setProperty("height", "100%", "important")
    return true
  }
  if (apply()) return
  // 面板由客户端状态渲染，可能晚于 load 事件，挂一个观察器等它出现。
  const observer = new MutationObserver(() => {
    if (apply()) observer.disconnect()
  })
  observer.observe(doc.documentElement, { childList: true, subtree: true })
}

type LlmConfig = {
  baseUrl: string
  apiKey: string
  model: string
}

type ModelConfigResponse = { llm: LlmConfig }

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`/api/v1${path}`, { credentials: "include", ...init })
  const d = await r.json()
  if (!r.ok) throw new Error(d.detail || "请求失败")
  return d
}

/** 学生端面板：与系统模型配置同款布局，左侧能力分区 + 右侧配置表单。 */
function StudentModelPanel({ open }: { open: boolean }) {
  const qc = useQueryClient()
  const saved = useQuery({
    queryKey: ["my-model-config"],
    queryFn: () => api<ModelConfigResponse>("/users/me/model-config"),
    enabled: open,
  })
  const existing = saved.data?.llm
  const hasKey = Boolean(existing?.apiKey)

  const [baseUrl, setBaseUrl] = useState("")
  const [apiKey, setApiKey] = useState("")
  const [model, setModel] = useState("")
  const [showKey, setShowKey] = useState(false)
  const [msg, setMsg] = useState("")
  const [error, setError] = useState("")
  const [loadedFor, setLoadedFor] = useState(false)

  // 每次打开时用服务端已保存的值初始化表单（API Key 不回显）。
  useEffect(() => {
    if (!open || loadedFor || !saved.isSuccess) return
    setLoadedFor(true)
    setBaseUrl(existing?.baseUrl ?? "https://open.bigmodel.cn/api/paas/v4")
    setModel(existing?.model ?? "glm-5.3-flash")
  }, [open, loadedFor, saved.isSuccess, existing])

  async function save() {
    setError("")
    setMsg("")
    if (!baseUrl.trim() || !apiKey.trim() || !model.trim()) {
      setError("请填写 Base URL、API Key 和模型名")
      return
    }
    try {
      await api("/users/me/model-config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          llm: {
            baseUrl: baseUrl.trim(),
            apiKey: apiKey.trim(),
            model: model.trim(),
          },
        }),
      })
      setMsg("已保存，课程学习中的 AI 引导将使用你配置的模型。")
      qc.invalidateQueries({ queryKey: ["my-model-config"] })
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败")
    }
  }

  return (
    <DialogContent
      className="flex h-[680px] max-w-4xl sm:max-w-4xl overflow-hidden p-0 gap-0"
      showCloseButton
    >
      <DialogTitle className="sr-only">模型配置</DialogTitle>

      {/* 左侧能力分区：学生端只保留语言模型 */}
      <div className="hidden w-48 shrink-0 flex-col gap-1.5 border-r bg-muted/30 p-3 sm:flex">
        <button
          type="button"
          className={cn(
            "flex w-full items-center gap-2.5 rounded-lg border px-3 py-2.5 text-left text-sm font-medium transition-all",
            "border-primary/50 bg-primary/5 shadow-sm",
          )}
        >
          <SlidersHorizontal className="h-4 w-4" />
          语言模型
        </button>
      </div>

      {/* 右侧配置表单 */}
      <div className="flex min-w-0 flex-1 flex-col overflow-y-auto p-6">
        {saved.isLoading ? (
          <div className="flex flex-1 items-center justify-center text-muted-foreground">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" /> 载入中…
          </div>
        ) : (
          <>
            <div className="mb-6">
              <h2 className="text-xl font-semibold">自定义模型</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                OpenAI 协议 · 支持智谱 GLM、DeepSeek、月之暗面等
                {hasKey && (
                  <span className="ml-2 inline-flex items-center rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs text-emerald-600">
                    已配置 {existing?.model}
                  </span>
                )}
              </p>
            </div>

            <div className="space-y-4">
              <div className="space-y-1">
                <label className="text-sm font-medium">API Base URL</label>
                <Input
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                  placeholder="https://open.bigmodel.cn/api/paas/v4"
                />
              </div>
              <div className="space-y-1">
                <label className="text-sm font-medium">API Key</label>
                <div className="relative">
                  <Input
                    type={showKey ? "text" : "password"}
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    placeholder={
                      hasKey ? "••••••（已保存，输入新值可覆盖）" : "sk-…"
                    }
                    className="pr-10"
                  />
                  <button
                    type="button"
                    onClick={() => setShowKey(!showKey)}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground"
                  >
                    {showKey ? (
                      <EyeOff className="size-4" />
                    ) : (
                      <Eye className="size-4" />
                    )}
                  </button>
                </div>
              </div>
              <div className="space-y-1">
                <label className="text-sm font-medium">模型名称</label>
                <Input
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  placeholder="glm-5.3-flash"
                />
                <p className="text-xs text-muted-foreground">
                  常用：智谱 glm-5.3-flash / DeepSeek deepseek-chat
                </p>
              </div>
            </div>

            <div className="mt-auto pt-6">
              {msg && <p className="pb-2 text-sm text-emerald-600">{msg}</p>}
              {error && <p className="pb-2 text-sm text-destructive">{error}</p>}
              <Button onClick={save}>保存</Button>
            </div>
          </>
        )}
      </div>
    </DialogContent>
  )
}
