import {
  BookOpenCheck,
  GraduationCap,
  Home,
  KeyRound,
  Presentation,
  Settings,
  UserCog,
} from "lucide-react"

import { SidebarAppearance } from "@/components/Common/Appearance"
import { Logo } from "@/components/Common/Logo"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
} from "@/components/ui/sidebar"
import useAuth from "@/hooks/useAuth"
import { teacherServiceUrl, usePlatformStatus } from "@/hooks/usePlatformStatus"
import { type Item, Main } from "./Main"
import { User } from "./User"

const studentItems: Item[] = [
  { icon: Home, title: "学生首页", path: "/student" },
  { icon: GraduationCap, title: "我的课程", path: "/my-courses" },
  { icon: KeyRound, title: "加入课程", path: "/join" },
]

function useAdminItems(): Item[] {
  const status = usePlatformStatus()
  const modelSettings = teacherServiceUrl(status.data?.teacherUrl, "/settings")
  return [
    { icon: UserCog, title: "用户管理", path: "/admin" },
    ...(modelSettings
      ? [
          {
            icon: Settings,
            title: "模型配置",
            path: modelSettings,
            external: true,
            badge: "系统配置",
          } as Item,
        ]
      : []),
  ]
}

/** Teacher navigation; 课程建设/授课管理 are served by the teacher workspace. */
function useTeacherItems(): Item[] {
  const status = usePlatformStatus()
  const courseBuilding = teacherServiceUrl(
    status.data?.teacherUrl,
    "/course-space",
  )
  const classTeaching = teacherServiceUrl(status.data?.teacherUrl, "/classes")
  return [
    { icon: Home, title: "产品首页", path: "/teacher" },
    ...(courseBuilding
      ? [
          {
            icon: BookOpenCheck,
            title: "课程建设",
            path: courseBuilding,
            external: true,
            badge: "教师工作区",
          } as Item,
        ]
      : []),
    ...(classTeaching
      ? [
          {
            icon: Presentation,
            title: "授课管理",
            path: classTeaching,
            external: true,
            badge: "教师工作区",
          } as Item,
        ]
      : []),
  ]
}

export function AppSidebar() {
  const { user: currentUser } = useAuth()

  const teacherItems = useTeacherItems()
  const adminItems = useAdminItems()
  const items = currentUser?.is_superuser
    ? adminItems
    : currentUser?.role === "teacher"
      ? teacherItems
      : studentItems

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="px-4 py-6 group-data-[collapsible=icon]:px-0 group-data-[collapsible=icon]:items-center">
        <Logo variant="responsive" />
      </SidebarHeader>
      <SidebarContent>
        <Main items={items} />
      </SidebarContent>
      <SidebarFooter>
        <SidebarAppearance />
        <User user={currentUser} />
      </SidebarFooter>
    </Sidebar>
  )
}

export default AppSidebar
