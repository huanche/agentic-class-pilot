import { test, expect } from "@playwright/test";

const playerUrl = "http://127.0.0.1:3107/classroom-player/room-2";
const summary = [{ id: "c", title: "计算机网络", lessons: [
  { id: "L1", title: "第一课", week: 1, lessonNumber: 1, playerUrl: null },
  { id: "L2", title: "分组交换与帧中继基础", week: 2, lessonNumber: 1, playerUrl: null },
] }];
const feedback = { summary: "保留本次学习反馈", points: [] };
const messages = [{ role: "student", text: "保留我的课堂复述", phase: "recall" }];
const postclassMessages = [{ role: "assistant", text: "保留我的课后对话", phase: "postclass-open" }];

async function boot(page, { entry = "catalog", missingUrl = false, completed = true, failures = 0, wrongCourse = false } = {}) {
  const courses = structuredClone(summary);
  courses[0].lessons[1] = { ...courses[0].lessons[1], playerUrl: missingUrl ? null : playerUrl, classroomId: "room-2" };
  const snapshot = Buffer.from(JSON.stringify({ lessonId: "L2", phase: "done" })).toString("base64url") + ".signature";
  const saved = { sessionId: "saved", lessonId: "L2", phase: "done", courses, feedback, messages,
    postclassMessages, postclassStage: "open", preparation: "ready", browserCourseKey: "u:c" };
  const catalog = { sessionId: "catalog", lessonId: null, phase: "idle", courses: summary,
    messages: [], browserCourseKey: "u:c" };
  const requests = [];
  let attempts = 0;
  await page.addInitScript(({ snapshot, entry, completed }) => {
    localStorage.setItem("student_browser_last_course_key", "u:c");
    localStorage.setItem("student_browser_token:u:c", "ticket");
    localStorage.setItem("student_browser_last_key", entry === "done" ? "u:c:L2" : "u:c:catalog");
    if (completed) localStorage.setItem("student_browser_snapshot:u:c:L2", snapshot);
  }, { snapshot, entry, completed });
  await page.route("**/classroom-player/**", route => route.fulfill({ contentType: "text/html", body: "<p>课堂播放器</p>" }));
  await page.route("**/api/session/**", async route => {
    const path = new URL(route.request().url()).pathname;
    requests.push(path);
    let body;
    let status = 200;
    if (path.endsWith("/platform-entry")) body = { freshSessionMode: true, platformUrl: "http://platform.example" };
    else if (path.endsWith("/start")) body = path.endsWith("/postclass/start") ? { ...saved, phase: "postclass" } : catalog;
    else if (path.endsWith("/browser-restore")) body = saved;
    else if (path.includes("/begin/")) body = { ...saved, phase: "video", feedback: null };
    else if (path.endsWith("/discussion")) body = { ...saved, phase: "discussion", agentStage: "wrapup" };
    else if (path.endsWith("/end")) body = saved;
    else if (path.endsWith("/playback")) {
      attempts += 1;
      status = attempts <= failures ? 503 : 200;
      body = status === 503 ? { detail: "平台服务暂不可用" }
        : { courseId: wrongCourse ? "other" : "c", lesson: { ...courses[0].lessons[1], playerUrl } };
    } else throw new Error(`Unexpected API call: ${path}`);
    await route.fulfill({ status, json: body });
  });
  await page.goto("/app/");
  return requests;
}

async function enterCompleted(page) {
  await page.getByRole("button", { name: /分组交换与帧中继基础/ }).click();
  await expect(page.getByText(feedback.summary)).toBeVisible();
}

async function expectReplay(page) {
  await expect(page.getByLabel("课后视频播放器").locator("iframe")).toHaveAttribute("src", `${playerUrl}?embedded=player&replay=1`);
  await expect(page.getByRole("main").getByRole("alert")).toHaveCount(0);
}

test("replay immediately after ending a lesson", async ({ page }) => {
  const requests = await boot(page, { completed: false });
  await page.getByRole("button", { name: /分组交换与帧中继基础/ }).click();
  await page.getByRole("button", { name: "开始或继续上课" }).click();
  await page.getByRole("button", { name: "进入复述与讨论 →" }).click();
  await page.getByRole("button", { name: "确定进入复述与讨论" }).click();
  await page.getByRole("button", { name: "结束本课并查看反馈" }).click();
  await page.getByRole("button", { name: "回看视频" }).click();
  await expectReplay(page);
  expect(requests.filter(path => path.endsWith("/playback"))).toHaveLength(0);
});

test("reenter completed lesson from catalog and retain feedback and conversation", async ({ page }) => {
  await boot(page);
  await enterCompleted(page);
  await page.getByRole("button", { name: "回看视频" }).click();
  await expectReplay(page);
  await page.getByRole("button", { name: "返回学习反馈" }).click();
  await expect(page.getByText(feedback.summary)).toBeVisible();
  await page.getByRole("button", { name: "与 AI 自由提问" }).click();
  await expect(page.getByText(postclassMessages[0].text)).toBeVisible();
  await page.getByRole("button", { name: "返回学习反馈" }).click();
  await page.getByRole("button", { name: "返回课时列表" }).click();
  await expect(page.getByRole("button", { name: /第一课/ })).toBeVisible();
  await enterCompleted(page);
  await page.getByRole("button", { name: "回看视频" }).click();
  await expectReplay(page);
});

test("fresh platform entry restores the completed lesson for replay", async ({ page }) => {
  await boot(page);
  const token = Buffer.from(JSON.stringify({ uid: "u", cid: "c" })).toString("base64url") + ".signature";
  await page.goto(`/app/?launch_token=${token}`);
  await enterCompleted(page);
  await page.getByRole("button", { name: "回看视频" }).click();
  await expectReplay(page);
});

test("reload directly into a completed lesson and replay", async ({ page }) => {
  await boot(page, { entry: "done" });
  await page.getByRole("button", { name: "回看视频" }).click();
  await expectReplay(page);
});

test("missing saved URL is fetched without restarting the lesson", async ({ page }) => {
  const requests = await boot(page, { missingUrl: true });
  await enterCompleted(page);
  await page.getByRole("button", { name: "回看视频" }).click();
  await expectReplay(page);
  expect(requests.filter(path => path.endsWith("/playback"))).toHaveLength(1);
  expect(requests.some(path => path.includes("/begin/"))).toBe(false);
});

test("failed playback lookup stays on feedback and can be retried", async ({ page }) => {
  await boot(page, { missingUrl: true, failures: 1 });
  await enterCompleted(page);
  await page.getByRole("button", { name: "回看视频" }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("平台服务暂不可用");
  await expect(page.getByText(feedback.summary)).toBeVisible();
  await expect(page.getByLabel("课后视频播放器")).toHaveCount(0);
  await page.getByRole("button", { name: "重试回看" }).click();
  await expectReplay(page);
});

test("playback response from another course is rejected", async ({ page }) => {
  await boot(page, { missingUrl: true, wrongCourse: true });
  await enterCompleted(page);
  await page.getByRole("button", { name: "回看视频" }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("播放信息与当前课时不匹配");
  await expect(page.getByText(feedback.summary)).toBeVisible();
  await expect(page.getByLabel("课后视频播放器")).toHaveCount(0);
});

test("player error returns to feedback with a retry action", async ({ page }) => {
  await boot(page);
  await enterCompleted(page);
  await page.getByRole("button", { name: "回看视频" }).click();
  await expectReplay(page);
  await page.frameLocator('iframe[title="课程播放器"]').locator("body").evaluate(() => {
    parent.postMessage({ type: "PLAYER_ERROR", message: "课堂播放器暂不可用" }, location.origin);
  });
  await expect(page.getByRole("main").getByRole("alert")).toContainText("课堂播放器暂不可用");
  await expect(page.getByText(feedback.summary)).toBeVisible();
  await page.getByRole("button", { name: "重试回看" }).click();
  await expectReplay(page);
});
