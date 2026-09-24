import { zodResolver } from "@hookform/resolvers/zod"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { useForm } from "react-hook-form"
import { z } from "zod"

import { EnrollmentsService } from "@/client"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
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

function JoinCourse() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const form = useForm<FormData>({
    resolver: zodResolver(formSchema),
    defaultValues: { code: "" },
  })

  const mutation = useMutation({
    mutationFn: (data: FormData) =>
      EnrollmentsService.joinCourse({ body: { code: data.code } }),
    onSuccess: (resp) => {
      showSuccessToast(`已加入课程「${resp.data.title}」`)
      queryClient.invalidateQueries({ queryKey: ["my-courses"] })
      navigate({ to: "/courses/$courseId", params: { courseId: resp.data.id } })
    },
    onError: handleError.bind(showErrorToast),
  })

  const onSubmit = (data: FormData) => {
    mutation.mutate(data)
  }

  return (
    <div className="mx-auto max-w-md pt-12">
      <Card>
        <CardHeader>
          <CardTitle>加入课程</CardTitle>
          <CardDescription>输入教师分享的 8 位选课码加入课程</CardDescription>
        </CardHeader>
        <CardContent>
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
                        className="uppercase tracking-widest font-mono"
                        maxLength={8}
                        {...field}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <LoadingButton type="submit" loading={mutation.isPending}>
                加入课程
              </LoadingButton>
            </form>
          </Form>
        </CardContent>
      </Card>
    </div>
  )
}
