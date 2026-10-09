import { expect, test } from "@playwright/test"

/**
 * 加入课程页(全屏沉浸式)回归 —— specs/001-join-course-page
 * join 接口用路由拦截桩住,不依赖真实选课码;登录态走 auth.setup。
 */

test("全屏沉浸式视觉与关键元素", async ({ page }) => {
  await page.goto("/join")

  await expect(page.getByRole("heading", { name: "加入课程" })).toBeVisible()
  await expect(page.getByText("输入教师分享的 8 位选课码")).toBeVisible()
  await expect(page.getByText("还没有选课码？找任课老师要一个。")).toBeVisible()

  const input = page.getByLabel("选课码")
  await expect(input).toBeEditable()

  // 覆盖层铺满视口(沉浸式全屏,盖住侧栏)
  const overlay = page.locator("div.fixed.inset-0")
  await expect(overlay).toBeVisible()
  const box = await overlay.boundingBox()
  expect(box?.width).toBeGreaterThanOrEqual(
    page.viewportSize()?.width ?? Number.MAX_SAFE_INTEGER,
  )
  expect(box?.height).toBeGreaterThanOrEqual(
    page.viewportSize()?.height ?? Number.MAX_SAFE_INTEGER,
  )
})

test("选课码输入自动大写并去除空格", async ({ page }) => {
  await page.goto("/join")

  const input = page.getByLabel("选课码")
  await input.fill("ab c1")

  await expect(input).toHaveValue("ABC1")
})

test("无效选课码:内联中文错误、输入保留、焦点回框", async ({ page }) => {
  await page.route("**/api/v1/enrollments/join", async (route) => {
    await route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({ detail: "选课码无效或已过期" }),
    })
  })

  await page.goto("/join")

  const input = page.getByLabel("选课码")
  await input.fill("ZZZZZZ9Z")
  await page.getByRole("button", { name: "加入课程" }).click()

  await expect(page.getByRole("alert")).toHaveText("选课码无效或已过期")
  await expect(input).toHaveValue("ZZZZZZ9Z")
  await expect(input).toBeFocused()
})

test("提交进行中防重复请求", async ({ page }) => {
  let hits = 0
  await page.route("**/api/v1/enrollments/join", async (route) => {
    hits += 1
    await new Promise((resolve) => setTimeout(resolve, 500))
    await route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({ detail: "选课码无效或已过期" }),
    })
  })

  await page.goto("/join")

  await page.getByLabel("选课码").fill("ZZZZZZ9Z")
  const submit = page.getByRole("button", { name: "加入课程" })
  await submit.click()
  await submit.click({ force: true }) // 二次点击(即便强制)不应再产生请求

  await expect(page.getByRole("alert")).toBeVisible()
  expect(hits).toBe(1)
})

/*
 * 「有效码成功加入 → 提示 + 跳转 + my-courses 刷新」需要动态课程 fixture,
 * 由 specs/001-join-course-page/quickstart.md 第 2 步人工走查覆盖(8088 入口)。
 */
