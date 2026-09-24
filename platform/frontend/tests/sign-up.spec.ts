import { expect, type Page, test } from "@playwright/test"

import { randomEmail, randomPassword } from "./utils/random"

test.use({ storageState: { cookies: [], origins: [] } })

const MAILPIT_API = "http://localhost:8025/api/v1"

// Read the latest verification code for an email from Mailpit (dev mailbox)
const getVerificationCode = async (
  page: Page,
  email: string,
): Promise<string> => {
  // wait briefly for the mail to arrive
  await page.waitForTimeout(1500)
  const list = await (await page.request.get(`${MAILPIT_API}/messages`)).json()
  const msg = list.messages.find((m: { To: { Address: string }[] }) =>
    m.To.some((t) => t.Address === email),
  )
  expect(msg, `no mail for ${email} in Mailpit`).toBeTruthy()
  const detail = await (
    await page.request.get(`${MAILPIT_API}/message/${msg.ID}`)
  ).json()
  const text: string = detail.HTML + (detail.Text ?? "")
  const match = text.match(/>(\d{6})</) ?? text.match(/\b(\d{6})\b/)
  expect(match, "no 6-digit code in mail").toBeTruthy()
  return match![1]
}

const fillForm = async (
  page: Page,
  full_name: string,
  email: string,
  password: string,
  confirm_password: string,
  code?: string,
) => {
  await page.getByTestId("full-name-input").fill(full_name)
  await page.getByTestId("email-input").fill(email)
  if (code !== undefined) {
    await page.getByTestId("code-input").fill(code)
  }
  await page.getByTestId("password-input").fill(password)
  await page.getByTestId("confirm-password-input").fill(confirm_password)
}

const verifyInput = async (page: Page, testId: string) => {
  const input = await page.getByTestId(testId)
  await expect(input).toBeVisible()
  await expect(input).toHaveText("")
  await expect(input).toBeEditable()
}

test("Inputs are visible, empty and editable", async ({ page }) => {
  await page.goto("/signup")

  await verifyInput(page, "full-name-input")
  await verifyInput(page, "email-input")
  await verifyInput(page, "code-input")
  await verifyInput(page, "password-input")
  await verifyInput(page, "confirm-password-input")
})

test("Sign Up button is visible", async ({ page }) => {
  await page.goto("/signup")

  await expect(page.getByRole("button", { name: "注册" })).toBeVisible()
})

test("Log In link is visible", async ({ page }) => {
  await page.goto("/signup")

  await expect(page.getByRole("link", { name: "去登录" })).toBeVisible()
})

test("Sign up with valid name, email, and password", async ({ page }) => {
  const full_name = "Test User"
  const email = randomEmail()
  const password = randomPassword()

  await page.goto("/signup")
  await page.getByTestId("email-input").fill(email)
  await page.getByTestId("send-code-button").click()
  const code = await getVerificationCode(page, email)
  await fillForm(page, full_name, email, password, password, code)
  await page.getByRole("button", { name: "注册" }).click()

  await expect(page).toHaveURL(/\/login$/)
})

test("Sign up with wrong verification code", async ({ page }) => {
  const full_name = "Test User"
  const email = randomEmail()
  const password = randomPassword()

  await page.goto("/signup")
  await page.getByTestId("email-input").fill(email)
  await page.getByTestId("send-code-button").click()
  await getVerificationCode(page, email) // ensure the mail arrived
  await fillForm(page, full_name, email, password, password, "000000")
  await page.getByRole("button", { name: "注册" }).click()

  await expect(page.getByText("验证码错误")).toBeVisible()
})

test("Sign up with invalid email", async ({ page }) => {
  await page.goto("/signup")

  await fillForm(
    page,
    "Playwright Test",
    "invalid-email",
    "changethis",
    "changethis",
  )
  await page.getByRole("button", { name: "注册" }).click()

  await expect(page.getByText("请输入有效的邮箱地址")).toBeVisible()
})

test("Send code with existing email", async ({ page }) => {
  await page.goto("/signup")

  // the seeded admin account is already registered
  await page.getByTestId("email-input").fill("admin@example.com")
  await page.getByTestId("send-code-button").click()

  await expect(page.getByText("该邮箱已被注册")).toBeVisible()
})

test("Sign up with weak password", async ({ page }) => {
  const email = randomEmail()

  await page.goto("/signup")
  await fillForm(page, "Playwright Test", email, "weak", "weak", "123456")
  await page.getByRole("button", { name: "注册" }).click()

  await expect(page.getByText("密码至少 8 位")).toBeVisible()
})

test("Sign up with mismatched passwords", async ({ page }) => {
  const email = randomEmail()

  await page.goto("/signup")
  await fillForm(
    page,
    "Test User",
    email,
    randomPassword(),
    randomPassword(),
    "123456",
  )
  await page.getByRole("button", { name: "注册" }).click()

  await expect(page.getByText("两次输入的密码不一致")).toBeVisible()
})

test("Sign up with missing full name", async ({ page }) => {
  await page.goto("/signup")

  await fillForm(
    page,
    "",
    randomEmail(),
    randomPassword(),
    randomPassword(),
    "123456",
  )
  await page.getByRole("button", { name: "注册" }).click()

  await expect(page.getByText("请输入姓名")).toBeVisible()
})

test("Sign up with missing email", async ({ page }) => {
  await page.goto("/signup")

  await fillForm(
    page,
    "Test User",
    "",
    randomPassword(),
    randomPassword(),
    "123456",
  )
  await page.getByRole("button", { name: "注册" }).click()

  await expect(page.getByText("请输入有效的邮箱地址")).toBeVisible()
})

test("Sign up with missing password", async ({ page }) => {
  await page.goto("/signup")

  await fillForm(page, "Test User", randomEmail(), "", "", "123456")
  await page.getByRole("button", { name: "注册" }).click()

  await expect(page.getByText("请输入密码")).toBeVisible()
})

test("Sign up with missing code", async ({ page }) => {
  await page.goto("/signup")

  await fillForm(page, "Test User", randomEmail(), "password123", "password123")
  await page.getByRole("button", { name: "注册" }).click()

  await expect(page.getByText("请输入 6 位验证码")).toBeVisible()
})
