import { Link } from "@tanstack/react-router"

import { cn } from "@/lib/utils"

interface LogoProps {
  variant?: "full" | "icon" | "responsive"
  className?: string
  asLink?: boolean
}

export function Logo({
  variant = "full",
  className,
  asLink = true,
}: LogoProps) {
  const mark = <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-white p-1 shadow-sm"><img src="/brand-mark.png" alt="" className="size-full object-contain" /></span>
  const content = variant === "icon" ? mark : (
    <span className={cn("inline-flex items-center gap-3", className)}>
      {mark}
      <span className="leading-tight group-data-[collapsible=icon]:hidden">
        <span className="block text-base font-semibold tracking-tight text-foreground">AI 教育平台</span>
        <span className="block text-[11px] font-medium tracking-wide text-muted-foreground">TEACH · LEARN · CREATE</span>
      </span>
    </span>
  )

  if (!asLink) {
    return content
  }

  return <Link to="/">{content}</Link>
}
