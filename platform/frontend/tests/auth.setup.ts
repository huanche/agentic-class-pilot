import { test as setup } from "@playwright/test"
import { firstSuperuser, firstSuperuserPassword } from "./config.ts"

const authFile = "playwright/.auth/user.json"

setup("authenticate", async ({ page }) => {
  await page.goto("/login")
  await page.getByTestId("email-input").fill(firstSuperuser)
  await page.getByTestId("password-input").fill(firstSuperuserPassword)
  await page.getByRole("button", { name: "登录" }).click()
  /* 登录后按角色跳转(teacher/student/admin),到达任意非 /login 页面即认证成功 */
  await page.waitForURL((url) => !url.pathname.startsWith("/login"))
  await page.context().storageState({ path: authFile })
})
