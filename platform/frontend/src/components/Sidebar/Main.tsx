import { Link as RouterLink, useRouterState } from "@tanstack/react-router"
import { ExternalLink } from "lucide-react"
import type { LucideIcon } from "lucide-react"

import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar"

export type Item = {
  icon: LucideIcon
  title: string
  path?: string
  /**
   * Internal items navigate through the router; external items (teacher
   * workspace, other services) render a plain anchor with the absolute URL.
   */
  external?: boolean
  /** Small marker for entries served by an external service (e.g. 教师工作区). */
  badge?: string
  /**
   * In-app action items (e.g. 模型配置 opens a dialog) render a plain button
   * instead of navigating. Takes precedence over path/external.
   */
  onSelect?: () => void
}

interface MainProps {
  items: Item[]
}

export function Main({ items }: MainProps) {
  const { isMobile, setOpenMobile } = useSidebar()
  const router = useRouterState()
  const currentPath = router.location.pathname

  const handleMenuClick = () => {
    if (isMobile) {
      setOpenMobile(false)
    }
  }

  return (
    <SidebarGroup>
      <SidebarGroupContent>
        <SidebarMenu>
          {items.map((item) => {
            const isActive = !item.external && item.path === currentPath

            return (
              <SidebarMenuItem key={item.title}>
                <SidebarMenuButton
                  tooltip={item.title}
                  isActive={isActive}
                  asChild
                >
                  {item.onSelect ? (
                    <button
                      type="button"
                      onClick={() => {
                        item.onSelect?.()
                        handleMenuClick()
                      }}
                    >
                      <item.icon />
                      <span>{item.title}</span>
                    </button>
                  ) : item.external ? (
                    <a href={item.path} onClick={handleMenuClick}>
                      <item.icon />
                      <span className="flex-1 truncate">{item.title}</span>
                      {item.badge && (
                        <span className="inline-flex items-center gap-1 rounded-full bg-[#B00055]/8 px-1.5 py-0.5 text-[10px] font-medium text-[#B00055]">
                          {item.badge}
                          <ExternalLink className="size-2.5" />
                        </span>
                      )}
                    </a>
                  ) : (
                    <RouterLink to={item.path} onClick={handleMenuClick}>
                      <item.icon />
                      <span>{item.title}</span>
                    </RouterLink>
                  )}
                </SidebarMenuButton>
              </SidebarMenuItem>
            )
          })}
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  )
}
