import { expect, test } from "@playwright/test";

/* 课后辅导最小闭环（开关默认开启）：
   视频最终播完 → 课堂自动进入 tutoring 阶段，复用聊天界面，
   AI 开场消息（知识点编号 + 征询意愿）自动到达，无需任何点击。

   独立态没有真实播放器（挂载区等待外部适配器），e2e 里由测试替
   播放器调用它播完时会调的同一个接口（POST /api/session/:id/media/done，
   final=true）——这正是"确定性桩"：被替掉的只有播放器，课堂链路全真。

   原有四阶段编排（复述→探究→讨论）= 开关关闭路径，见
   classroom-flow.spec.js（由 playwright.legacy.config.mjs 以
   AGENT_POST_VIDEO_TUTORING=0 运行）。
*/
const JOIN_CODE = "OSK7M3";

function freshNumber() {
  return "9" + String(Date.now()).slice(-8);
}

async function registerAndJoin(page, number) {
  /* 学生端挂在 /app（basePath）；“/” 是教师端调试控制台。 */
  await page.goto("/app");
  await expect(page.locator(".login__card")).toBeVisible();

  await page.getByRole("button", { name: "注册", exact: true }).click();
  await page.locator("#login-number").fill(number);
  await page.locator("#login-name").fill("测试学生");
  await page.locator("#login-password").fill("hunter2");
  await page.getByRole("button", { name: "注册并进入", exact: true }).click();

  await expect(page.locator("#enroll-code")).toBeVisible();
  await page.locator("#enroll-code").fill(JOIN_CODE);
  await page.getByRole("button", { name: "加入课程", exact: true }).click();
  await expect(page.locator(".join-fab")).toBeVisible();
}

/** 走到教学视频页：开课 → 点「开始播放教学视频」。 */
async function reachVideoStage(page, number) {
  await registerAndJoin(page, number);
  await page.getByRole("button", { name: /操作系统/ }).click();
  await page.locator(".week-tile").click();
  await page.locator('[data-goto="class"]').click();
  await page.locator("#btn-start").click();
  await expect(page.getByRole("button", { name: /开始播放教学视频/ })).toBeVisible();
  await page.getByRole("button", { name: /开始播放教学视频/ }).click();
  await expect(page.locator("#stage-video")).toBeVisible();
}

/** 替播放器上报「视频最终播完」。返回会话号。 */
async function reportVideoDone(page) {
  const sid = await page.evaluate(
    () => localStorage.getItem("ai-learn.sessionId.ch3-process-scheduling")
  );
  expect(sid).toBeTruthy();
  const done = await page.request.post(`/api/session/${sid}/media/done`, { data: {} });
  expect(done.ok()).toBeTruthy();
  return sid;
}

test("video completion enters tutoring chat with the numbered opening", async ({ page }) => {
  await reachVideoStage(page, freshNumber());
  await reportVideoDone(page);

  // 不进复述界面：课堂直接切到辅导，复用聊天 UI（含输入框）
  await expect(page.locator("#stage-summary")).toBeHidden();
  await expect(page.locator("#stage-chat")).toBeVisible({ timeout: 10_000 });
  await expect(page.locator("#class-badge")).toHaveText("课后辅导");

  // AI 开场消息自动到达（轮询链路投递）：知识点固定编号 + 征询意愿
  await expect(page.locator("#chat-log")).toContainText("1. 调度是什么", { timeout: 10_000 });
  await expect(page.locator("#chat-log")).toContainText("6. 时间片轮转与多级反馈队列");
  await expect(page.locator("#chat-log")).toContainText("顺序");

  // 学生无需任何确认按钮即可直接说话（CI 无模型 → 确定性骨架回复）
  const aiBefore = await page.locator("#chat-log .msg--ai").count();
  await page.locator("#composer-input").fill("先复习 2，我给自己 3 星，复习 15 分钟。");
  await page.locator("#composer-send").click();
  await expect(page.locator("#chat-log .msg--ai")).toHaveCount(aiBefore + 1, { timeout: 15_000 });
  await expect(page.locator("#composer-input")).toBeEnabled();

  // 辅导阶段不会被切走
  await expect(page.locator("#class-badge")).toHaveText("课后辅导");
  await expect(page.locator("#stage-chat")).toBeVisible();
});

test("refreshing mid-tutoring restores the same tutoring session", async ({ page }) => {
  await reachVideoStage(page, freshNumber());
  await reportVideoDone(page);
  await expect(page.locator("#stage-chat")).toBeVisible({ timeout: 10_000 });
  await expect(page.locator("#chat-log")).toContainText("1. 调度是什么", { timeout: 10_000 });

  // F5：辅导会话原样恢复（同一会话号、同一阶段、开场消息还在）
  await page.reload();
  await expect(page.locator("#stage-chat")).toBeVisible({ timeout: 10_000 });
  await expect(page.locator("#class-badge")).toHaveText("课后辅导");
  await expect(page.locator("#chat-log")).toContainText("1. 调度是什么", { timeout: 10_000 });
});

test("explicit end shows feedback on review page and resume reopens chat", async ({ page }) => {
  await reachVideoStage(page, freshNumber());
  await reportVideoDone(page);
  await expect(page.locator("#stage-chat")).toBeVisible({ timeout: 10_000 });
  await expect(page.locator("#chat-log")).toContainText("1. 调度是什么", { timeout: 10_000 });

  // 明确结束 → 下课总结（done 阶段）→ 去课后（按钮文案「去看看掌握情况」）
  await page.locator("#composer-input").fill("今天就到这");
  await page.locator("#composer-send").click();
  await expect(page.locator("#stage-done")).toBeVisible({ timeout: 15_000 });

  // 下课页知识点 = 固定编号目录（与辅导同源，6 条），不是课时文件的 8 条静态清单
  await expect(page.locator("#done-kps .done__kp")).toHaveCount(6);
  await expect(page.locator("#done-kps")).toContainText("调度是什么");
  await expect(page.locator("#done-kps")).toContainText("时间片轮转与多级反馈队列");

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
