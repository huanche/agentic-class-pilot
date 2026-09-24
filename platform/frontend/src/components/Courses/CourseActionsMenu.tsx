import { EllipsisVertical } from "lucide-react"
import { useState } from "react"

import type { CoursePublic } from "@/client"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import DeleteCourse from "./DeleteCourse"
import EditCourse from "./EditCourse"

interface CourseActionsMenuProps {
  course: CoursePublic
}

export const CourseActionsMenu = ({ course }: CourseActionsMenuProps) => {
  const [open, setOpen] = useState(false)

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon">
          <EllipsisVertical />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <EditCourse course={course} onSuccess={() => setOpen(false)} />
        <DeleteCourse
          id={course.id}
          title={course.title}
          onSuccess={() => setOpen(false)}
        />
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
