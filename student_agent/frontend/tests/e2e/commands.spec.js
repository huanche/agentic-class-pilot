import { test, expect } from "@playwright/test";

async function setup(page, failure) {
  const commands = [];
  let applied = 0;
  let receipt;
  const courses = [{ id: "c", title: "课程", lessons: [{ id: "lesson", title: "命令回归课时", week: 1 }] }];
  const snapshot = Buffer.from(JSON.stringify({ lessonId: "lesson", phase: "discussion" })).toString("base64url") + ".signature";
  let current = { sessionId: "s", userId: "u", lessonId: "lesson", phase: "discussion", agentStage: "recall",
    stateVersion: 1, contentGeneration: 0, courses, messages: [], preparation: "ready",
    browserCourseKey: "u:c", browserKey: "u:c:lesson", browserSnapshot: snapshot };
  const statusQueries = [];
  await page.addInitScript(() => {
    localStorage.setItem("student_last_course:u", "c");
    if (!localStorage.getItem("student_browser_last_key:u")) localStorage.setItem("student_browser_last_key:u", "u:c:catalog");
  });
  await page.route("**/api/session/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/identity")) return route.fulfill({json:{userId:"u",csrfToken:"test-csrf"}});
    if (path.endsWith("/platform-entry")) return route.fulfill({ json: { platformUrl: "http://platform.example" } });
    if (path === "/api/session/start") return route.fulfill({ json: {
      sessionId: "catalog", userId: "u", phase: "idle", courses, messages: [], stateVersion: 0, browserCourseKey: "u:c" } });
    if (path.endsWith("/resume") || path === "/api/session/s") return route.fulfill({ json: current });
    if (path.endsWith("/status")) {
      statusQueries.push(path);
      return route.fulfill({ json: receipt });
    }
    if (path === "/api/session/s/commands") {
      const body = route.request().postDataJSON();
      commands.push(body);
      if (failure === "model" && commands.length === 1) {
        current = { ...current, stateVersion: 2,
          pendingSubmission: { ...body, status: "failed" } };
        receipt = { commandId: body.commandId, status: "failed", sessionView: current,
          failure: { code: "MODEL_UNAVAILABLE", detail: "模型暂不可用" } };
        return route.fulfill({ status: 503, json: receipt });
      }
      if (!receipt || receipt.status !== "completed") {
        applied++;
        current = { ...current, stateVersion: 3, pendingSubmission: null, messages: [
          { role: "student", phase: "recall", text: body.payload.text },
          { role: "assistant", phase: "recall", text: "命令已保存的回复" }] };
        receipt = { commandId: body.commandId, status: "completed", sessionView: current };
      }
      if (failure === "lost-response" && commands.length === 1) return route.abort("failed");
      return route.fulfill({ json: receipt });
    }
    throw new Error(`Unexpected request: ${path}`);
  });
  await page.goto("/app/");
  await page.getByRole("button", { name: /命令回归课时/ }).click();
  await expect(page.getByRole("textbox", { name: "输入复述或讨论" })).toBeVisible();
  return { commands, statusQueries, applied: () => applied };
}

test("retry after a lost response reuses its command and displays one answer", async ({ page }) => {
  const state = await setup(page, "lost-response");
  await page.getByRole("textbox").fill("原始回答");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.getByRole("textbox")).toHaveValue("原始回答");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.getByRole("log").getByText("命令已保存的回复", { exact: false })).toBeVisible();
  expect(state.commands).toHaveLength(2);
  expect(state.commands[0]).toEqual(state.commands[1]);
  expect(state.applied()).toBe(1);
  await expect(page.getByText("原始回答", { exact: true })).toHaveCount(1);
});

test("reload confirms the completed command after a lost response", async ({ page }) => {
  const state = await setup(page, "lost-response");
  await page.getByRole("textbox").fill("刷新前回答");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.getByRole("textbox")).toHaveValue("刷新前回答");
  await page.reload();
  await expect(page.getByRole("log").getByText("命令已保存的回复", { exact: false })).toBeVisible();
  expect(state.commands).toHaveLength(1);
  expect(state.statusQueries.length).toBeGreaterThanOrEqual(1);
  expect(new Set(state.statusQueries).size).toBe(1);
  expect(state.applied()).toBe(1);
});

test("failed model call survives reload and retries the original submission", async ({ page }) => {
  const state = await setup(page, "model");
  await page.getByRole("textbox").fill("失败后保留的回答");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.getByText("模型暂不可用", { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("textbox")).toHaveValue("失败后保留的回答");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.getByRole("log").getByText("命令已保存的回复", { exact: false })).toBeVisible();
  expect(state.commands).toHaveLength(2);
  expect(state.commands[0]).toEqual(state.commands[1]);
  expect(state.applied()).toBe(1);
});
