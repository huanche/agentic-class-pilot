import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { useEffect, useState } from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"

import { EnrollmentsService } from "@/client"
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form"
import { Input } from "@/components/ui/input"
import { LoadingButton } from "@/components/ui/loading-button"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

const formSchema = z.object({
  code: z.string().min(4, { message: "请输入教师提供的选课码" }),
})

type FormData = z.infer<typeof formSchema>

export const Route = createFileRoute("/_layout/join")({
  component: JoinCourse,
  head: () => ({
    meta: [{ title: "加入课程 - AI 教育平台" }],
  }),
})

/* 学生端选课页同款学位帽图形(28px,线性 1.5 描边) */
function GradCapIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      className="size-7 text-primary"
      aria-hidden="true"
    >
      <path d="M3 9.5 12 5l9 4.5-9 4.5-9-4.5Z" />
      <path d="M7 12v4.5c0 1.1 2.2 2 5 2s5-.9 5-2V12" />
      <path d="M20 10.5v5" />
    </svg>
  )
}

function JoinCourse() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { showSuccessToast } = useCustomToast()
  const [serverError, setServerError] = useState<string | null>(null)

  const form = useForm<FormData>({
    resolver: zodResolver(formSchema),
    defaultValues: { code: "" },
  })

  /* 失败后焦点回到输入框,输入值保留(表单不 reset) */
  useEffect(() => {
    if (serverError) form.setFocus("code")
  }, [serverError, form])

  const mutation = useMutation({
    mutationFn: (data: FormData) =>
      EnrollmentsService.joinCourse({ body: { code: data.code } }),
    onSuccess: (resp) => {
      showSuccessToast(`已加入课程「${resp.data.title}」`)
      queryClient.invalidateQueries({ queryKey: ["my-courses"] })
      navigate({ to: "/courses/$courseId", params: { courseId: resp.data.id } })
    },
    onError: (error) =>
      handleError.call((message: string) => {
        setServerError(
          message === "Network Error" ? "网络连接失败，请检查网络后重试" : message,
        )
      }, error),
  })

  const onSubmit = (data: FormData) => {
    mutation.mutate(data)
  }

  return (
    <div
      className="fixed inset-0 z-[400] flex items-center justify-center overflow-hidden bg-background p-6"
      role="dialog"
      aria-modal="true"
      aria-labelledby="join-title"
    >
      {/* 柔光背景:与学生端选课页同款 radial 渐变(酒红 10% → 透明) */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(ellipse 70% 50% at 50% 0%, color-mix(in oklab, var(--primary) 10%, transparent) 0%, transparent 70%)",
        }}
      />
      <style>{`@keyframes joinCardIn { from { opacity: 0; transform: translateY(16px) scale(0.97); } to { opacity: 1; transform: none; } }`}</style>

      <section
        className="relative z-[1] w-full max-w-[380px] rounded-2xl border bg-card/80 p-8 shadow-lg backdrop-blur-[20px] saturate-[1.3]"
        style={{ animation: "joinCardIn 0.5s ease-out both" }}
      >
        <span className="mx-auto mb-[18px] grid size-14 place-items-center rounded-full bg-primary/10">
          <GradCapIcon />
        </span>
        <h1
          id="join-title"
          className="text-center text-[19px] font-semibold tracking-tight"
        >
          加入课程
        </h1>
        <p className="mb-6 mt-1 text-center text-[13px] text-muted-foreground">
          输入教师分享的 8 位选课码
        </p>

        <Form {...form}>
          <form
            onSubmit={form.handleSubmit(onSubmit)}
            className="flex flex-col gap-4"
          >
            <FormField
              control={form.control}
              name="code"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>选课码</FormLabel>
                  <FormControl>
                    <Input
                      placeholder="例如：32TIMC3U"
                      className="font-mono tracking-widest"
                      maxLength={8}
                      autoFocus
                      {...field}
                      onChange={(e) => {
                        /* 输入侧统一大写、去空格(data-model 约束) */
                        field.onChange(
                          e.target.value.toUpperCase().replace(/\s+/g, ""),
                        )
                        if (serverError) setServerError(null)
                      }}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            {serverError ? (
              <p className="text-sm font-medium text-destructive" role="alert">
                {serverError}
              </p>
            ) : null}
            <LoadingButton
              type="submit"
              loading={mutation.isPending}
              className="w-full"
            >
              加入课程
            </LoadingButton>
          </form>
        </Form>

        <p className="mt-5 text-center text-[13px] text-muted-foreground">
          还没有选课码？找任课老师要一个。
        </p>
      </section>
    </div>
  )
}
