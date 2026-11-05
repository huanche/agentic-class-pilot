import { test, expect } from "@playwright/test";

test("pilot uses server tasks, evidence feedback and the original conversation space", async ({ page }) => {
  const courses = [{ id: "c", title: "课程", lessons: [{ id: "lesson", title: "动态试点课时", week: 1 }] }];
  const commands = [];
  const snapshot = Buffer.from(JSON.stringify({ lessonId: "lesson", phase: "discussion" })).toString("base64url") + ".signature";
  let current = { sessionId: "s", userId: "u", lessonId: "lesson", phase: "discussion", agentStage: "tutoring",
    flowVersion: "dynamic_dialogue_v1", currentTaskPublic: { taskId: "task-1" },
    activityStatus: "active", allowedCommands: ["submit_answer", "request_help", "ask_question", "pause", "finish"],
    progressSummary: { discussed: 0, total: 2 }, learningProgress: null,
    stateVersion: 1, contentGeneration: 0, courses, messages: [{ role: "assistant", text: "请解释判断依据", messageId: "m1" }],
    preparation: "ready", browserCourseKey: "u:c", browserKey: "u:c:lesson", browserSnapshot: snapshot };
  await page.addInitScript(() => {
    localStorage.setItem("student_last_course:u", "c");
    localStorage.setItem("student_browser_last_key:u", "u:c:catalog");
  });
  await page.route("**/api/session/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/identity")) return route.fulfill({json:{userId:"u",csrfToken:"test-csrf"}});
    if (path.endsWith("/platform-entry")) return route.fulfill({ json: { platformUrl: "http://platform.example" } });
    if (path.endsWith("/start")) return route.fulfill({ json: { sessionId: "catalog", userId: "u", phase: "idle", courses,
      messages: [], stateVersion: 0, browserCourseKey: "u:c" } });
    if (path.endsWith("/resume") || path === "/api/session/s") return route.fulfill({ json: current });
    if (path.endsWith("/commands")) {
      const body = route.request().postDataJSON();
      commands.push(body);
      if (body.type === "submit_answer") {
        current = { ...current, stateVersion: 3, agentStage: "independent_attempt",
          currentTaskPublic: { taskId: "task-2" }, progressSummary: { discussed: 1, total: 2 },
          messages: [...current.messages, { role: "student", text: body.payload.text, messageId: "m2" },
            { role: "assistant", text: "请在新情境下解释选择", messageId: "m3" }] };
      } else if (body.type === "finish") {
        current = { ...current, phase: "done", stateVersion: 5, agentStage: "wrapup", feedback: {
          flowVersion: "dynamic_dialogue_v1", summary: "只根据本次表达和帮助记录反馈。",
          points: [{ id: "p", title: "判断条件", label: "已有交流记录", evidence: "我的具体解释", suggestion: "继续核对适用条件。" }],
          assisted: [], unresolved: [{ observationId: "o1", questions: "尚需说明适用条件" }], contentLimitations: [] } };
      } else throw new Error(`Unexpected command: ${body.type}`);
      return route.fulfill({ json: { commandId: body.commandId, status: "completed", sessionView: current } });
    }
    throw new Error(`Unexpected request: ${path}`);
  });
  await page.goto("/app/");
  await page.getByRole("button", { name: /动态试点课时/ }).click();
  await page.getByRole("textbox").fill("我的具体解释");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.getByRole("log")).toContainText("请在新情境下解释选择");
  expect(commands[0].payload.taskId).toBe("task-1");
  await expect(page.getByLabel("课堂阶段进度")).toContainText("独立尝试");
  await expect(page.getByLabel("课堂阶段进度")).toContainText("已有表达的主题 1 / 2");
  await page.getByRole("button", { name: "结束本课并查看反馈", exact: true }).click();
  await expect(page.getByRole("heading", { name: "本次交流记录" })).toBeVisible();
  await expect(page.getByText("尚需说明适用条件", { exact: true })).toBeVisible();
  await expect(page.getByText(/首轮复述 0 次/)).toHaveCount(0);
  await expect(page.getByText("提前结束仅限测试使用", { exact: true })).toHaveCount(0);
  expect(commands[1].type).toBe("finish");
});
