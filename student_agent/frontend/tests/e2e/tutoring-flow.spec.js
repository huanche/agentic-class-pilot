import { createHmac } from "node:crypto";
import { expect, test } from "@playwright/test";

/* 课后辅导最小闭环（开关默认开启）：
   视频最终播完 → 课堂自动进入 tutoring 阶段，复用聊天界面，
   AI 开场消息（知识点编号 + 征询意愿）自动到达，无需任何点击。

   学生端平台化后没有独立登录流：e2e 走平台深链——测试用共享的
   STUDENT_SERVICE_KEY 签发 launch_token（与学生端验签同算法），
   learning-context 由 tests/e2e/platform-stub.mjs 桩返回 ch3 夹具。
   播放器由测试替它调用播完接口（POST media/done，final=true）：
   被替掉的只有播放器与平台，课堂链路全真。

   原有四阶段编排（复述→探究→讨论）= 开关关闭路径，见
   classroom-flow.spec.js（由 playwright.legacy.config.mjs 以
   AGENT_POST_VIDEO_TUTORING=0 运行）。
*/
const SERVICE_KEY = "e2e-stub-key";
const COURSE_ID = "ch3-sched-course-e2e";
const PUBLICATION = { publicationId: "ch3sched", version: 1 };

test("顶部仅展示知识点，星级在结束、报告、反馈和续聊后保持一致", async ({ page }) => {
  test.skip(process.env.MASTERY_E2E !== "1", "此用例使用本地模型桩验证评分，不调用真实模型");
  await reachVideoStage(page);
  const sid = await reportVideoDone(page);
  await expect(page.locator("#stage-chat")).toBeVisible();
  const send = async text => {
    const response = await page.request.post(`/api/session/${sid}/message`, {data: {text}});
    expect(response.ok()).toBeTruthy();
    return response.json();
  };
  await send("准备好了");
  const right = await send("调度负责选择处理机使用者");
  expect(right.stars["kp-001"]).toBe(4);
  await expect(page.locator(".tm-item").filter({hasText: "调度是什么"})).toBeVisible();
  await expect(page.locator(".tm-stars, .tm-review, .tm-rubric")).toHaveCount(0);

  async function finishAndVerify(stars) {
    await page.locator("#composer-input").fill("今天就到这");
    await page.locator("#composer-send").click();
    await expect(page.locator("#stage-done")).toBeVisible();
    const state = await (await page.request.get(`/api/session/${sid}/state`)).json();
    expect(state.stars["kp-001"]).toBe(stars);
    await page.locator("#done-to-review").click();
    await expect(page.locator(".report__kp").first()).toContainText(stars === 4 ? "能独立说清" : "能灵活应用");
    await expect(page.locator(".tfeedback__kp").first()).toContainText(`掌握 ${stars}★`);
    const report = await (await page.request.get(`/api/session/${sid}/export?fmt=json`)).json();
    const feedback = await (await page.request.get(`/api/session/${sid}/tutoring-report`)).json();
    expect(report.knowledge_points.find(k => k.kp_id === "kp-001").stars).toBe(stars);
    expect(feedback.payload.knowledge_points.find(k => k.kp_id === "kp-001").system_stars).toBe(stars);
  }
  await finishAndVerify(4);
  await page.getByRole("button", {name: "继续辅导"}).click();
  await expect(page.locator("#stage-chat")).toBeVisible();
  await send("先复习 1");
  const state = await (await page.request.get(`/api/session/${sid}/state`)).json();
  expect(state.tutoring.question.text).toContain("关键条件发生变化");
  const applied = await send("条件改变时应重新选择合适的策略，因为目标和约束已经发生改变");
  expect(applied.stars["kp-001"]).toBe(5);
  await expect(page.locator(".tm-item").filter({hasText: "调度是什么"})).toBeVisible();
  await expect(page.locator(".tm-stars, .tm-review, .tm-rubric")).toHaveCount(0);
  await finishAndVerify(5);
  const metrics = await (await page.request.get("http://127.0.0.1:8878/mock-llm/metrics")).json();
  expect(metrics.endReassessments).toBe(0);
});

/** 平台深链入口：签一枚 launch_token（与 launch_context.verify 同算法）。 */
function launchEntry(prefix = "e2e-") {
  const payload = {
    uid: prefix + String(Date.now()).slice(-8) + String(Math.random()).slice(2, 6),
    cid: COURSE_ID, rid: null, pub: PUBLICATION,
    exp: Math.floor(Date.now() / 1000) + 3600,
  };
  const payloadJson = JSON.stringify(payload);
  const encoded = Buffer.from(payloadJson, "utf8").toString("base64url");
  const signature = createHmac("sha256", SERVICE_KEY).update(payloadJson).digest("hex");
  return `/app?launch_token=${encodeURIComponent(encoded + "." + signature)}`;
}

test("selecting the second lesson binds its player and tutoring knowledge", async ({ page }) => {
  await page.goto(launchEntry("scope-"));
  await expect(page.locator(".week-tile")).toHaveCount(2);
  await page.locator(".week-tile").filter({hasText: "第二课时"}).click();
  await page.locator('[data-goto="class"]').click();
  await expect(page.locator("#class-title")).toContainText("第二课时");
  await page.locator("#btn-start").click();
  await page.getByRole("button", {name: /开始播放教学视频/}).click();
  await expect(page.locator("iframe").first()).toHaveAttribute("src", /player-second/);
  const sid = await reportVideoDone(page);
  await expect(page.locator("#chat-log")).toContainText("第二课时专属概念");
  await expect(page.locator("#chat-log")).not.toContainText("调度是什么");
  const report = await (await page.request.get(`/api/session/${sid}/export?fmt=json`)).json();
  expect(report.lesson_id).toBe("lesson-second");
  expect(report.knowledge_points.map(point => point.kp_id)).toEqual(["kp-second"]);
});

/** 走到教学视频页：平台深链进学生端（单课课程自动落到选课时页）→ 开课 → 播放。 */
async function reachVideoStage(page) {
  await page.goto(launchEntry());
  await expect(page.locator(".week-tile")).toBeVisible({ timeout: 15_000 });
  await page.locator(".week-tile").click();
  await page.locator('[data-goto="class"]').click();
  await page.locator("#btn-start").click();
  await expect(page.getByRole("button", { name: /开始播放教学视频/ })).toBeVisible();
  await page.getByRole("button", { name: /开始播放教学视频/ }).click();
  await expect(page.locator("#stage-video")).toBeVisible();
}

/** 替播放器上报「视频最终播完」。返回会话号。 */
async function reportVideoDone(page) {
  const sid = await page.evaluate(() => {
    const key = Object.keys(localStorage).find((k) => k.startsWith("ai-learn.sessionId."));
    return key ? localStorage.getItem(key) : null;
  });
  expect(sid).toBeTruthy();
  const done = await page.request.post(`/api/session/${sid}/media/done`, { data: {} });
  expect(done.ok()).toBeTruthy();
  return sid;
}

test("video completion enters tutoring chat with the numbered opening", async ({ page }) => {
  await reachVideoStage(page);
  await reportVideoDone(page);

  // 不进复述界面：课堂直接切到辅导，复用聊天 UI（含输入框）
  await expect(page.locator("#stage-summary")).toBeHidden();
  await expect(page.locator("#stage-chat")).toBeVisible({ timeout: 10_000 });
  await expect(page.locator("#class-badge")).toHaveText("课后辅导");

  // AI 开场消息自动到达（轮询链路投递）：知识点固定编号 + 征询意愿
  await expect(page.locator("#chat-log")).toContainText("1. 调度是什么", { timeout: 10_000 });
  await expect(page.locator("#chat-log")).toContainText("6. 时间片轮转与多级反馈队列");
  await expect(page.locator("#chat-log")).toContainText("顺序");
  await expect(page.locator("#chat-log")).not.toContainText("自评");

  // 学生无需任何确认按钮即可直接说话（CI 无模型 → 确定性骨架回复）
  const aiBefore = await page.locator("#chat-log .msg--ai").count();
  await page.locator("#composer-input").fill("先复习 2，再 1，复习 15 分钟。");
  await page.locator("#composer-send").click();
  await expect(page.locator("#chat-log .msg--ai")).toHaveCount(aiBefore + 1, { timeout: 15_000 });
  await expect(page.locator("#composer-input")).toBeEnabled();
  const tutoring = await page.evaluate(async () => {
    const lessonId = location.hash.split("/").at(-1);
    const sid = localStorage.getItem("ai-learn.sessionId." + decodeURIComponent(lessonId));
    return (await (await fetch(`/api/session/${encodeURIComponent(sid)}/state`)).json()).tutoring;
  });
  expect(tutoring.order.slice(0, 2)).toEqual([2, 1]);
  expect(tutoring.planned_minutes).toBe(15);
  expect(tutoring).not.toHaveProperty("self_ratings");
  await expect(page.locator(".tm-self")).toHaveCount(0);

  // 辅导阶段不会被切走
  await expect(page.locator("#class-badge")).toHaveText("课后辅导");
  await expect(page.locator("#stage-chat")).toBeVisible();
});

test("refreshing mid-tutoring restores the same tutoring session", async ({ page }) => {
  await reachVideoStage(page);
  const sid = await reportVideoDone(page);
  await expect(page.locator("#stage-chat")).toBeVisible({ timeout: 10_000 });
  await expect(page.locator("#chat-log")).toContainText("1. 调度是什么", { timeout: 10_000 });

  // F5：辅导会话原样恢复（同一会话号、同一阶段、开场消息还在）
  const rebound = page.waitForRequest((request) => request.method() === "POST"
    && request.url().endsWith("/api/session/start") && request.postDataJSON().session_id === sid);
  await page.reload();
  // 旧课堂也重新绑定已校验的平台上下文，空知识点目录才能被补齐。
  await rebound;
  await expect(page.locator("#stage-chat")).toBeVisible({ timeout: 10_000 });
  await expect(page.locator("#class-badge")).toHaveText("课后辅导");
  await expect(page.locator("#chat-log")).toContainText("1. 调度是什么", { timeout: 10_000 });
});

test("explicit end shows feedback on review page and resume reopens chat", async ({ page }) => {
  await reachVideoStage(page);
  await reportVideoDone(page);
  await expect(page.locator("#stage-chat")).toBeVisible({ timeout: 10_000 });
  await expect(page.locator("#chat-log")).toContainText("1. 调度是什么", { timeout: 10_000 });

  // 明确结束 → 下课总结（done 阶段）→ 去课后（按钮文案「去看看掌握情况」）
  await page.locator("#composer-input").fill("今天就到这");
  await page.locator("#composer-send").click();
  await expect(page.locator("#stage-done")).toBeVisible({ timeout: 15_000 });
  await page.locator("#done-to-review").click();

  // 课后页：辅导反馈卡（第 1 版）+ 继续辅导入口
  await expect(page.locator(".tfeedback__title")).toContainText("第 1 版", { timeout: 15_000 });
  await expect(page.locator(".tfeedback")).toContainText("复习约");

  // 继续辅导：回原会话的聊天界面，还能继续说话
  await page.getByRole("button", { name: "继续辅导" }).click();
  await expect(page.locator("#stage-chat")).toBeVisible({ timeout: 10_000 });
  await expect(page.locator("#class-badge")).toHaveText("课后辅导");
  const aiBefore = await page.locator("#chat-log .msg--ai").count();
  await page.locator("#composer-input").fill("再讲讲第 3 个知识点");
  await page.locator("#composer-send").click();
  await expect(page.locator("#chat-log .msg--ai")).toHaveCount(aiBefore + 1, { timeout: 15_000 });
});
