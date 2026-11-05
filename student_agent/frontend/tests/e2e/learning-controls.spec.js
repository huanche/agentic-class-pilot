import { test, expect } from "@playwright/test";

async function pilot(page, { failHelp = false } = {}) {
  const courses = [{ id: "c", title: "课程", lessons: [{ id: "L", title: "交互试点课时", week: 1 }] }];
  const allowed = ["submit_answer", "request_help", "ask_question", "pause", "finish"];
  const snapshot = Buffer.from(JSON.stringify({ lessonId: "L", phase: "discussion" })).toString("base64url") + ".sig";
  let current = { sessionId: "s", userId: "u", lessonId: "L", phase: "discussion", courses, flowVersion: "dynamic_dialogue_v1",
    agentStage: "tutoring", activityStatus: "active", allowedCommands: allowed, stateVersion: 1, contentGeneration: 0,
    messages: [{ role: "assistant", text: "原题：说明你的判断依据", messageId: "original" }],
    currentTaskPublic: { taskId: "task-1" }, preparation: "ready",
    browserKey: "u:c:L", browserCourseKey: "u:c", browserSnapshot: snapshot };
  const commands = [];
  let failed = false;
  await page.addInitScript(() => {
    localStorage.setItem("student_last_course:u", "c");
    if (!localStorage.getItem("student_browser_last_key:u")) localStorage.setItem("student_browser_last_key:u", "u:c:catalog");
  });
  await page.route("**/api/session/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/identity")) return route.fulfill({json:{userId:"u",csrfToken:"test-csrf"}});
    if (path.endsWith("/platform-entry")) return route.fulfill({ json: { platformUrl: "https://platform.test" } });
    if (path === "/api/session/start") return route.fulfill({ json: { sessionId: "catalog", userId: "u", phase: "idle", courses,
      messages: [], stateVersion: 0, browserCourseKey: "u:c" } });
    if (path === "/api/session/resume" || path === "/api/session/s") return route.fulfill({ json: current });
    if (path.endsWith("/commands")) {
      const body = route.request().postDataJSON(); commands.push(body);
      if (body.type === "request_help" && failHelp && !failed) {
        failed = true;
        current = { ...current, stateVersion: 2, pendingSubmission: { ...body, status: "failed" } };
        return route.fulfill({ status: 503, json: { commandId: body.commandId, status: "failed", sessionView: current,
          failure: { code: "MODEL_UNAVAILABLE", detail: "提示暂不可用，请重试" } } });
      }
      current = { ...current, stateVersion: current.stateVersion + 2, pendingSubmission: null };
      if (body.type === "pause") current = { ...current, activityStatus: "paused", allowedCommands: ["resume_activity", "finish"] };
      else if (body.type === "resume_activity") current = { ...current, activityStatus: "active", allowedCommands: allowed };
      else if (["request_help", "ask_question", "submit_answer"].includes(body.type)) current = { ...current, messages: [...current.messages,
        { role: "student", text: body.payload.text, messageId: `student-${commands.length}` },
        { role: "assistant", text: body.type === "request_help" ? "这是已记录的帮助" : "已记录本次表达", messageId: `assistant-${commands.length}` }] };
      else throw new Error(`Unexpected command: ${body.type}`);
      return route.fulfill({ json: { commandId: body.commandId, status: "completed", sessionView: current } });
    }
    throw new Error(`Unexpected request: ${path}`);
  });
  await page.goto("/app/");
  await page.getByRole("button", { name: /交互试点课时/ }).click();
  await expect(page.getByRole("textbox")).toBeVisible();
  return { commands, set: patch => { current = { ...current, ...patch }; } };
}

test("hints, examples and questions use typed commands bound to the displayed task", async ({ page }) => {
  const state = await pilot(page);
  await page.getByRole("button", { name: "给个提示", exact: true }).click();
  await expect(page.getByRole("log")).toContainText("这是已记录的帮助");
  await page.getByRole("button", { name: "举个例子", exact: true }).click();
  await expect(page.getByRole("log").getByText("这是已记录的帮助", { exact: true })).toHaveCount(2);
  await page.getByRole("textbox").fill("这个条件是什么意思？");
  await page.getByRole("button", { name: "提出问题", exact: true }).click();
  await expect(page.getByRole("log")).toContainText("已记录本次表达");
  expect(state.commands.map(c => c.type)).toEqual(["request_help", "request_help", "ask_question"]);
  expect(state.commands.map(c => c.payload.taskId)).toEqual(["task-1", "task-1", "task-1"]);
  expect(state.commands[1].payload.text).toContain("例子");
  expect(state.commands[2].payload.text).toBe("这个条件是什么意思？");
});

test("pause survives reload and resume keeps the original task without sending another prompt", async ({ page }) => {
  const state = await pilot(page);
  await page.getByRole("button", { name: "暂停学习", exact: true }).click();
  await expect(page.getByRole("textbox")).toBeDisabled();
  await expect(page.getByRole("button", { name: "继续学习", exact: true })).toBeEnabled();
  await page.reload();
  await expect(page.getByRole("textbox")).toBeDisabled();
  await page.getByRole("button", { name: "继续学习", exact: true }).click();
  await expect(page.getByRole("textbox")).toBeEnabled();
  await expect(page.getByRole("log").getByText("原题：说明你的判断依据", { exact: true })).toHaveCount(1);
  expect(state.commands.map(c => c.type)).toEqual(["pause", "resume_activity"]);
  expect(state.commands.every(c => Object.keys(c.payload).length === 0)).toBe(true);
});

test("a failed help request retries its original identity after reload without becoming an answer draft", async ({ page }) => {
  const state = await pilot(page, { failHelp: true });
  await page.getByRole("button", { name: "给个提示", exact: true }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("提示暂不可用");
  await page.reload();
  await expect(page.getByRole("textbox")).toHaveValue("");
  await page.getByRole("button", { name: "给个提示", exact: true }).click();
  await expect(page.getByRole("log")).toContainText("这是已记录的帮助");
  expect(state.commands).toHaveLength(2);
  expect(state.commands[0]).toEqual(state.commands[1]);
});

test("focus refresh reflects another device pausing or finishing without creating a command", async ({ page }) => {
  const state = await pilot(page);
  state.set({ stateVersion: 3, activityStatus: "paused", allowedCommands: ["resume_activity", "finish"] });
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(page.getByRole("textbox")).toBeDisabled();
  await expect(page.getByRole("button", { name: "继续学习", exact: true })).toBeVisible();
  state.set({ stateVersion: 5, phase: "done", agentStage: "wrapup", teachingStage: "completed",
    allowedCommands: ["continue_after_class", "reset_lesson"] });
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(page.getByRole("heading", { name: "本节课结束" })).toBeVisible();
  expect(state.commands).toHaveLength(0);
});
