import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation } from "@tanstack/react-query"
import {
  createFileRoute,
  Link as RouterLink,
  redirect,
} from "@tanstack/react-router"
import { useEffect, useState } from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"
import { UsersService } from "@/client"
import { AuthLayout } from "@/components/Common/AuthLayout"
import { Button } from "@/components/ui/button"
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
import { PasswordInput } from "@/components/ui/password-input"
import useAuth, { isLoggedIn } from "@/hooks/useAuth"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

const formSchema = z
  .object({
    email: z.email({ message: "请输入有效的邮箱地址" }),
    full_name: z.string().min(1, { message: "请输入姓名" }),
    password: z
      .string()
      .min(1, { message: "请输入密码" })
      .min(8, { message: "密码至少 8 位" }),
    confirm_password: z.string().min(1, { message: "请再次输入密码" }),
    role: z.enum(["student", "teacher"]),
    code: z.string().length(6, { message: "请输入 6 位验证码" }),
  })
  .refine((data) => data.password === data.confirm_password, {
    message: "两次输入的密码不一致",
    path: ["confirm_password"],
  })

type FormData = z.infer<typeof formSchema>

export const Route = createFileRoute("/signup")({
  component: SignUp,
  beforeLoad: async () => {
    if (isLoggedIn()) {
      throw redirect({
        to: "/",
      })
    }
  },
  head: () => ({
    meta: [
      {
        title: "注册 - AI 教育平台",
      },
    ],
  }),
})

function SignUp() {
  const { signUpMutation } = useAuth()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [countdown, setCountdown] = useState(0)

  useEffect(() => {
    if (countdown <= 0) return
    const timer = setTimeout(() => setCountdown((c) => c - 1), 1000)
    return () => clearTimeout(timer)
  }, [countdown])
  const form = useForm<FormData>({
    resolver: zodResolver(formSchema),
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: {
      email: "",
      full_name: "",
      password: "",
      confirm_password: "",
      role: "student",
      code: "",
    },
  })

  const sendCodeMutation = useMutation({
    mutationFn: (email: string) =>
      UsersService.sendVerificationCode({ body: { email } }),
    onSuccess: () => {
      showSuccessToast("验证码已发送，请查收邮件")
      setCountdown(60)
    },
    onError: handleError.bind(showErrorToast),
  })

  const onSendCode = async () => {
    const valid = await form.trigger("email")
    if (!valid) return
    sendCodeMutation.mutate(form.getValues("email"))
  }

  const onSubmit = (data: FormData) => {
    if (signUpMutation.isPending) return

    // exclude confirm_password from submission data
    const { confirm_password: _confirm_password, ...submitData } = data
    signUpMutation.mutate(submitData)
  }

  return (
    <AuthLayout>
      <Form {...form}>
        <form
          onSubmit={form.handleSubmit(onSubmit)}
          className="flex flex-col gap-6"
        >
          <div className="flex flex-col items-center gap-2 text-center">
            <h1 className="text-2xl font-bold">注册账号</h1>
          </div>

          <div className="grid gap-4">
            <FormField
              control={form.control}
              name="full_name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>姓名</FormLabel>
                  <FormControl>
                    <Input
                      data-testid="full-name-input"
                      placeholder="张三"
                      type="text"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="email"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>邮箱</FormLabel>
                  <div className="flex gap-2">
                    <FormControl>
                      <Input
                        data-testid="email-input"
                        placeholder="user@example.com"
                        type="email"
                        {...field}
                      />
                    </FormControl>
                    <Button
                      type="button"
                      variant="outline"
                      className="shrink-0"
                      disabled={countdown > 0 || sendCodeMutation.isPending}
                      onClick={onSendCode}
                      data-testid="send-code-button"
                    >
                      {countdown > 0 ? `${countdown}s 后重发` : "获取验证码"}
                    </Button>
                  </div>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="code"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>验证码</FormLabel>
                  <FormControl>
                    <Input
                      data-testid="code-input"
                      placeholder="邮件中的 6 位验证码"
                      maxLength={6}
                      inputMode="numeric"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="password"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>密码</FormLabel>
                  <FormControl>
                    <PasswordInput
                      data-testid="password-input"
                      placeholder="至少 8 位"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="confirm_password"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>确认密码</FormLabel>
                  <FormControl>
                    <PasswordInput
                      data-testid="confirm-password-input"
                      placeholder="再次输入密码"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="role"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>身份</FormLabel>
                  <FormControl>
                    <div className="flex gap-4">
                      {(
                        [
                          ["student", "学生"],
                          ["teacher", "教师"],
                        ] as const
                      ).map(([value, label]) => (
                        <label
                          key={value}
                          className="flex items-center gap-2 text-sm cursor-pointer"
                        >
                          <input
                            type="radio"
                            data-testid={`role-${value}`}
                            checked={field.value === value}
                            onChange={() => field.onChange(value)}
                          />
                          {label}
                        </label>
                      ))}
                    </div>
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <LoadingButton
              type="submit"
              className="w-full"
              loading={signUpMutation.isPending}
            >
              注册
            </LoadingButton>
          </div>

          <div className="text-center text-sm">
            已有账号？{" "}
            <RouterLink to="/login" className="underline underline-offset-4">
              去登录
            </RouterLink>
          </div>
        </form>
      </Form>
    </AuthLayout>
  )
}
