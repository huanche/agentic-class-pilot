import { Appearance } from "@/components/Common/Appearance"
import { Logo } from "@/components/Common/Logo"
import { Footer } from "./Footer"

interface AuthLayoutProps {
  children: React.ReactNode
}

export function AuthLayout({ children }: AuthLayoutProps) {
  return (
    <div className="min-h-svh bg-[radial-gradient(circle_at_15%_12%,rgba(176,0,85,.13),transparent_32%),radial-gradient(circle_at_90%_90%,rgba(59,130,246,.10),transparent_34%),#fcf8fa] p-4 dark:bg-[#130b10] md:p-6">
      <div className="mx-auto grid min-h-[calc(100svh-2rem)] max-w-6xl overflow-hidden rounded-[28px] border border-white/80 bg-white/75 shadow-[0_35px_90px_-45px_rgba(98,23,59,.38)] backdrop-blur-xl lg:grid-cols-2 dark:border-white/10 dark:bg-slate-950/70">
      <div className="relative hidden overflow-hidden bg-[#B00055] p-12 text-white lg:flex lg:flex-col lg:justify-between">
        <div className="absolute -right-24 -top-20 size-80 rounded-full bg-white/10 blur-3xl" />
        <Logo variant="full" className="relative [&>span:last-child>span]:text-white [&>span:last-child>span:last-child]:text-white/65" asLink={false} />
        <div className="relative max-w-md space-y-5"><p className="text-sm font-semibold tracking-[.18em] text-white/70">AI EDUCATION PLATFORM</p><h1 className="text-4xl font-semibold leading-tight">让备课、教学与学习在同一空间发生。</h1><p className="text-base leading-7 text-white/75">教师智能体帮助组织课程内容；学生智能体将陪伴每一次学习。</p></div>
        <p className="relative text-sm text-white/60">统一身份 · 统一课程 · 统一数据</p>
      </div>
      <div className="flex flex-col gap-4 p-6 md:p-10">
        <div className="flex justify-between lg:justify-end">
          <div className="lg:hidden"><Logo variant="full" asLink={false} /></div>
          <Appearance />
        </div>
        <div className="flex flex-1 items-center justify-center">
          <div className="w-full max-w-xs">{children}</div>
        </div>
        <Footer />
      </div>
      </div>
    </div>
  )
}
