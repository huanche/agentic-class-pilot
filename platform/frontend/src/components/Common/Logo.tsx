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
  const mark = <span className="grid size-9 place-items-center rounded-xl bg-[#B00055] text-lg font-bold text-white shadow-lg shadow-[#B00055]/25">A</span>
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
