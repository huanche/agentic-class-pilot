import { test, expect } from "@playwright/test";

async function setup(page, pendingAnswer = false, delayAcknowledgement = false, topicDirectory = false) {
  const courses = [{ id: "c", title: "课程", lessons: [{ id: "lesson", title: "三类型课时", week: 1 }] }];
  const feedback = mastered => ({ typedTeaching: true, schemaVersion: 4,
    summary: mastered ? "本课 2 个知识点：2 个已掌握，0 个待巩固。" : "本课 2 个知识点：1 个已掌握，1 个待巩固。",
    points: [{ id: "m", title: "栈的基本操作", category: "mastered", label: "已掌握", knownParts: ["能说明 Push 和 Pop 的作用"], gaps: [] },
      { id: "d", title: "设计操作序列", category: mastered ? "mastered" : "needs_review", label: mastered ? "已掌握" : "待巩固",
        knownParts: ["能写出操作序列"], gaps: mastered ? [] : ["某一步取走了非栈顶元素"], suggestion: mastered ? "" : "从出错步骤继续，先标出栈顶。" }] });
  let current = { sessionId: "s", userId: "u", lessonId: "lesson", courses, phase: "discussion", typedTeaching: true,
    flowVersion: "legacy_recall_v3", agentStage: "recall", stateVersion: 1, contentGeneration: 0,
    currentTaskPublic: { taskId: "task-1" }, preparation: "ready", postclassMessages: [],
    messages: [{ role: "assistant", text: "请构造操作序列。", phase: "recall" }],
    learningProgress: { total: 2, recallCompleted: 1, currentPoint: "设计操作序列" } };
  if (topicDirectory) Object.assign(current, {
    topicTitles: { m: "栈的基本操作", d: "设计操作序列" },
    taskTopics: { "task-1": "d", "task-first": "m", "task-reinforce": "d" },
    currentTaskPublic: { taskId: "task-1", topicId: "d" },
    messages: [
      { role: "assistant", text: "第一个知识点的开场", phase: "recall", taskId: "task-first", messageId: "first" },
      { role: "assistant", text: "上一段课堂对话\n".repeat(60), phase: "recall", taskId: "task-first", messageId: "history" },
      { role: "assistant", text: "请构造操作序列。", phase: "recall", taskId: "task-1", messageId: "second" },
    ],
  });
  if (topicDirectory) {
    for (let index = 1; index <= 24; index++) {
      const id = `extra-${index}`;
      current.topicTitles[id] = `知识点 ${index}`;
      current.taskTopics[id] = id;
      current.messages.push({ role: "assistant", text: `介绍知识点 ${index}`, phase: "recall", taskId: id, messageId: id });
    }
  }
  const commands = [];
  let releaseAcknowledgement;
  const acknowledgement = new Promise(resolve => { releaseAcknowledgement = resolve; });
  commands.releaseAcknowledgement = releaseAcknowledgement;
  await page.addInitScript(() => localStorage.setItem("student_last_course:u", "c"));
  await page.route("**/api/session/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/session/presence") {
      expect(route.request().method()).toBe("POST");
      expect(route.request().headers()["x-csrf-token"]).toBeTruthy();
      return route.fulfill({ status: 204 });
    }
    if (path.endsWith("/identity")) return route.fulfill({ json: { userId: "u", csrfToken: "test-csrf" } });
    if (path.endsWith("/presence")) return route.fulfill({ status: 204 });
    if (path.endsWith("/platform-entry")) return route.fulfill({ json: { platformUrl: "http://platform.test" } });
    if (path === "/api/session/start") return route.fulfill({ json: { sessionId: "catalog", userId: "u", phase: "idle", courses, messages: [], stateVersion: 0 } });
    if (path.endsWith("/resume") || path === "/api/session/s") return route.fulfill({ json: current });
    if (path.endsWith("/status")) return route.fulfill({ json: { status: "processing", sessionView: current } });
    if (path.endsWith("/commands")) {
      const body = route.request().postDataJSON(); commands.push(body);
      if (delayAcknowledgement && body.type === "finish" && body.expectedStateVersion !== current.stateVersion) {
        return route.fulfill({ status: 409, json: { code: "VERSION_CONFLICT", detail: "学习状态已更新，请刷新后重试" } });
      }
      current = { ...current, stateVersion: current.stateVersion + 2 };
      if (body.type === "submit_answer" && topicDirectory) current = { ...current, agentStage: "reinforce",
        currentTaskPublic: { taskId: "task-reinforce", topicId: "d" },
        messages: [...current.messages, { role: "student", text: body.payload.text, phase: "recall", taskId: "task-1" },
          { role: "assistant", text: "补强阶段的开场", phase: "reinforce", taskId: "task-reinforce", messageId: "reinforce" }] };
      else if (body.type === "submit_answer") current = { ...current, agentStage: "wrapup",
        messages: [...current.messages, { role: "student", text: body.payload.text }, { role: "assistant", text: "本次学习已结束，仍有需要巩固的步骤。" }] };
      else if (body.type === "finish") current = { ...current, phase: "done", feedback: feedback(false), pendingSubmission: null,
        ...(current.postclassStage ? { postclassStage: "paused" } : {}) };
      else if (body.type === "continue_after_class") current = { ...current, phase: "done", postclassStage: current.afterClassComplete ? "completed" : "remediation",
        currentTaskPublic: { taskId: "task-2" },
        postclassMessages: [{ role: "assistant", text: "接着原题，先标出出错一步的栈顶。", phase: "postclass-remediation" }] };
      else if (body.type === "postclass_answer") {
        if (delayAcknowledgement) {
          current = { ...current, pendingSubmission: { ...body, status: "processing" } };
          const accepted = structuredClone(current);
          await acknowledgement;
          return route.fulfill({ json: { commandId: body.commandId, status: "processing", sessionView: accepted } }).catch(() => {});
        }
        if (pendingAnswer) return route.fulfill({ json: { commandId: body.commandId, status: "processing", sessionView: current } });
        current = { ...current, afterClassComplete: true, postclassStage: "completed", feedback: feedback(true) };
      } else throw new Error(`Unexpected command: ${body.type}`);
      return route.fulfill({ json: { commandId: body.commandId, status: "completed", sessionView: current } });
    }
    throw new Error(`Unexpected request: ${path}`);
  });
  await page.goto("/app/");
  await page.getByRole("button", { name: /三类型课时/ }).click();
  return commands;
}

test("topic directory jumps within one chat and keeps recall and reinforcement separate", async ({ page }) => {
  const commands = await setup(page, false, false, true);
  const directory = page.getByRole("navigation", { name: "知识点对话位置" });
  await expect(directory.getByRole("button", { name: "设计操作序列" })).toHaveCount(1);
  await page.getByRole("textbox").fill("当前草稿");
  await expect(page.getByText("请构造操作序列。")).not.toBeInViewport();
  await directory.getByRole("button", { name: "设计操作序列" }).click();
  await expect(page.getByText("请构造操作序列。")).toBeInViewport();
  await directory.getByRole("button", { name: "栈的基本操作" }).click();
  await expect(page.getByText("第一个知识点的开场")).toBeInViewport();
  await expect(page.getByRole("textbox")).toHaveValue("当前草稿");
  expect(commands).toHaveLength(0);
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(directory.getByRole("heading", { name: "补强未掌握点" })).toBeVisible();
  await expect(directory.getByRole("button", { name: "设计操作序列" })).toHaveCount(2);
  await directory.getByRole("button", { name: "设计操作序列" }).last().click();
  await expect(page.getByText("补强阶段的开场")).toBeInViewport();
  await expect(page.getByRole("log")).toHaveCount(1);
  expect(commands.map(command => command.type)).toEqual(["submit_answer"]);

  const controls = directory.getByRole("group", { name: "切换知识点" });
  const list = directory.locator(".conversation-topics__list");
  const controlsTop = (await controls.boundingBox()).y;
  await list.hover();
  await page.mouse.wheel(0, -420);
  await expect.poll(() => list.evaluate(node => node.scrollTop)).toBeLessThan(300);
  await page.mouse.wheel(0, 420);
  await expect.poll(() => list.evaluate(node => node.scrollTop)).toBeGreaterThan(300);
  expect((await controls.boundingBox()).y).toBe(controlsTop);
});

async function finishClass(page) {
  await page.getByRole("textbox").fill("我的操作还有一个错误");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await page.getByRole("button", { name: "结束本课并查看反馈", exact: true }).click();
}

test("typed feedback shows abilities, gaps and next steps without rounds; completed entry does not restart", async ({ page }) => {
  const commands = await setup(page);
  await expect(page.getByLabel("课堂阶段进度")).not.toContainText("深入讨论");
  await finishClass(page);
  const feedback = page.getByRole("region", { name: "本课学习反馈" });
  await expect(feedback).toContainText("能说明 Push 和 Pop 的作用");
  await expect(feedback).toContainText("某一步取走了非栈顶元素");
  await expect(feedback).toContainText("从出错步骤继续，先标出栈顶。");
  await expect(feedback).not.toContainText(/轮数|首轮复述|星级|分数/);
  await page.getByRole("button", { name: "继续巩固", exact: true }).click();
  await expect(page.getByRole("log")).toContainText("接着原题");
  await page.getByRole("textbox").fill("我现在能自己修正并说明原因");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.getByText("本课知识点已全部掌握。", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "继续巩固", exact: true }).click();
  await expect(page.getByText("本课知识点已全部掌握。", { exact: true })).toBeVisible();
  await expect(page.getByRole("textbox")).toHaveCount(0);
  expect(commands.filter(command => command.type === "postclass_answer")).toHaveLength(1);
});

test("exit remains available while a postclass answer is processing and returns to feedback", async ({ page }) => {
  const commands = await setup(page, true);
  await finishClass(page);
  await page.getByRole("button", { name: "继续巩固", exact: true }).click();
  await page.getByRole("textbox").fill("还在思考的回答");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect.poll(() => commands.some(command => command.type === "postclass_answer")).toBeTruthy();
  const exit = page.getByRole("button", { name: "退出巩固并保留进度", exact: true });
  await expect(exit).toBeEnabled();
  await exit.click();
  await expect(page.getByRole("heading", { name: "本课学习反馈" })).toBeVisible();
  expect(commands.at(-1).type).toBe("finish");
  await expect(page.getByText("本课知识点已全部掌握。", { exact: true })).toHaveCount(0);
});

test("student can exit even when the answer acceptance acknowledgement has not arrived", async ({ page }) => {
  const commands = await setup(page, true, true);
  try {
    await finishClass(page);
    await page.getByRole("button", { name: "继续巩固", exact: true }).click();
    await page.getByRole("textbox").fill("等待服务器接收回执的回答");
    await page.getByRole("button", { name: "发送", exact: true }).click();
    await expect.poll(() => commands.some(command => command.type === "postclass_answer")).toBeTruthy();
    await page.getByRole("button", { name: "退出巩固并保留进度", exact: true }).click();
    await expect(page.getByRole("heading", { name: "本课学习反馈" })).toBeVisible();
    await expect(page.getByText("学习状态已更新，请刷新后重试", { exact: true })).toHaveCount(0);
    await expect(page.getByText("本课知识点已全部掌握。", { exact: true })).toHaveCount(0);
  } finally {
    commands.releaseAcknowledgement();
  }
});
