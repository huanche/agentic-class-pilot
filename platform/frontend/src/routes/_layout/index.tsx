import { createFileRoute, redirect } from "@tanstack/react-router"

import { UsersService } from "@/client"

export const Route = createFileRoute("/_layout/")({
  beforeLoad: async () => {
    const user = (await UsersService.readUserMe()).data
    if (user.is_superuser && user.role !== "teacher") {
      throw redirect({ to: "/admin", replace: true })
    }
    throw redirect({
      to: user.role === "teacher" ? "/teacher" : "/student",
      replace: true,
    })
  },
})
