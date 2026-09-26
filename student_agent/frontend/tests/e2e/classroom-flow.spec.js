import { expect, test } from "@playwright/test";

/* 学生端现在是「自注册 + 课程码加入」：
   1. 学生自己注册（学号 + 姓名 + 密码）
   2. 用老师给的课程码加入课程
   3. 之后才进得了课堂

   课程码来自 lesson-data/join-codes.json（预置了内置课时的码）。
   每次跑用随机学号 —— 账户在服务端持久化，写死学号第二次跑就会 409。
*/
const JOIN_CODE = "OSK7M3";

function freshNumber() {
  return "9" + String(Date.now()).slice(-8);
}

/** 注册一个新学生并用课程码加入课程，停在应用可用状态。 */
async function registerAndJoin(page, number) {
  await page.goto("/");
  await expect(page.locator(".login__card")).toBeVisible();

  await page.getByRole("button", { name: "注册", exact: true }).click();
  await page.locator("#login-number").fill(number);
  await page.locator("#login-name").fill("测试学生");
  await page.locator("#login-password").fill("hunter2");
  await page.getByRole("button", { name: "注册并进入", exact: true }).click();

  // 新账号一门课都没有 → 落到「加入课程」这一步
  await expect(page.locator("#enroll-code")).toBeVisible();
  await page.locator("#enroll-code").fill(JOIN_CODE);
  await page.getByRole("button", { name: "加入课程", exact: true }).click();
  await expect(page.locator(".join-fab")).toBeVisible();
}

test("a student can register, then join a course with the teacher's code", async ({ page }) => {
  const number = freshNumber();
  await page.goto("/");
  await expect(page.locator(".login__card")).toBeVisible();

  // 注册前应用本体不该挂载 —— 否则首屏会闪一下内容再被遮罩盖住
  await expect(page.locator('[data-goto="class"]')).toHaveCount(0);

  await page.getByRole("button", { name: "注册", exact: true }).click();
  await page.locator("#login-number").fill(number);
  await page.locator("#login-name").fill("测试学生");
  await page.locator("#login-password").fill("hunter2");
  await page.getByRole("button", { name: "注册并进入", exact: true }).click();

  // 一门课都没有：必须先进课程码这一步，没有退路
  await expect(page.locator("#enroll-code")).toBeVisible();
  await expect(page.getByRole("button", { name: "稍后再说" })).toHaveCount(0);

  await page.locator("#enroll-code").fill("ZZZZZZ");
  await page.getByRole("button", { name: "加入课程", exact: true }).click();
  await expect(page.locator(".login__error")).toContainText("课程码无效");

  await page.locator("#enroll-code").fill(JOIN_CODE);
  await page.getByRole("button", { name: "加入课程", exact: true }).click();

  // 进来了，而且课程目录里能看到刚加入的这门课
  // （[data-goto="class"] 在 hub 里，要选了课时才可见，这里不点它）
  await expect(page.locator(".join-fab")).toBeVisible();
  await page.getByRole("button", { name: /操作系统/ }).click();
  await expect(page.locator(".week-tile")).toBeVisible();
});

test("waiting for the AI shows the typing dots, and they go away when it answers", async ({ page }) => {
  // CI 里 AGENT_LLM_API_KEY="" 走确定性降级，响应是瞬间的，看不到等待态。
  // 所以这里自己把接口拖慢，模拟真实大模型的延迟。
  await page.route("**/api/session/*/message", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1200));
    await route.continue();
  });

  await registerAndJoin(page, freshNumber());
  await page.getByRole("button", { name: /操作系统/ }).click();
  await page.locator(".week-tile").click();
  await page.locator('[data-goto="class"]').click();
  await page.locator("#btn-start").click();
  await page.getByRole("button", { name: /开始播放教学视频/ }).click();
  await page.locator("#btn-skip-video").click();
  await expect(page.locator("#stage-summary")).toBeVisible();

  // 复述、探究两幕原来都没有等待反馈，只有输入框变灰
  await page.locator("#summary-input").fill("调度就是决定多个就绪进程谁先使用 CPU 的规则。");
  await page.locator("#summary-submit").click();
  await expect(page.locator("#summary-log [data-typing]")).toHaveCount(1);
  await expect(page.locator("#summary-log [data-typing] .typing span")).toHaveCount(3);

  // 回复到了，点必须消失 —— 别压在 AI 消息上面
  await expect(page.locator("#summary-log [data-typing]")).toHaveCount(0, { timeout: 15_000 });
  // 复述阶段是连贯对话：答完一轮输入框还在，可以接着答下一个问题
  await expect(page.locator("#summary-input")).toBeEnabled();

  // 测试用的推进按钮（正常情况下这一幕由后端 judge_advance 自己结束）
  await page.locator("#summary-next").click();
  await expect(page.locator("#stage-reflect")).toBeVisible();
  await page.locator("#reflect-input").fill("没有调度时，一个进程可能长期占用 CPU，其他任务无法及时响应。");
  await page.locator("#reflect-submit").click();
  await expect(page.locator("#reflect-log [data-typing]")).toHaveCount(1);
});

test("关掉窗口重开是一节新课，按 F5 不是", async ({ page, context }) => {
  // 这两件事在时间上分不出来（关窗再启动通常也在两分钟以内），
  // 靠 sessionStorage 区分：它能挺过 F5，但关掉标签页/窗口就清空。
  const KEY = "ai-learn.sessionId.ch3-process-scheduling";

  await registerAndJoin(page, freshNumber());
  await page.getByRole("button", { name: /操作系统/ }).click();
  await page.locator(".week-tile").click();
  await page.locator('[data-goto="class"]').click();
  await page.locator("#btn-start").click();
  await page.getByRole("button", { name: /开始播放教学视频/ }).click();
  await page.locator("#btn-skip-video").click();
  await expect(page.locator("#stage-summary")).toBeVisible();

  const before = await page.evaluate((k) => localStorage.getItem(k), KEY);
  expect(before).toBeTruthy();

  // 同一页刷新 → 学生上到一半的课不能丢
  await page.reload();
  await page.waitForTimeout(2000);
  expect(await page.evaluate((k) => localStorage.getItem(k), KEY)).toBe(before);

  // 关掉窗口、重新开一个 → 从头开始
  await page.close();
  const reopened = await context.newPage();
  await reopened.goto("/");
  await expect(reopened.locator(".join-fab")).toBeVisible();
  await reopened.getByRole("button", { name: /操作系统/ }).click();
  await reopened.locator(".week-tile").click();
  await reopened.locator('[data-goto="class"]').click();
  await reopened.waitForTimeout(2000);

  expect(await reopened.evaluate((k) => localStorage.getItem(k), KEY)).not.toBe(before);
  await expect(reopened.locator("#btn-start")).toBeVisible();       // 回到「开始上课」
  await expect(reopened.locator("#stage-summary")).toBeHidden();    // 不再是复述界面
});

test("student can move through all classroom stages and end after reflection", async ({ page }) => {
  await registerAndJoin(page, freshNumber());

  await page.getByRole("button", { name: /操作系统/ }).click();
  await page.locator(".week-tile").click();
  await page.locator('[data-goto="class"]').click();

  await expect(page.locator("#lesson-title")).toContainText("处理机调度");
  await expect(page.locator("#btn-start")).toBeEnabled();
  await page.locator("#btn-start").click();

  await expect(page.locator("#stage-chat")).toBeVisible();
  await expect(page.getByRole("button", { name: /开始播放教学视频/ })).toBeVisible();
  await page.getByRole("button", { name: /开始播放教学视频/ }).click();
  await expect(page.locator("#stage-video")).toBeVisible();

  await page.locator("#btn-skip-video").click();
  await expect(page.locator("#stage-summary")).toBeVisible();
  await page.locator("#summary-input").fill("调度负责决定多个就绪进程谁先使用 CPU，以及运行多长时间。");
  await page.locator("#summary-submit").click();
  await expect(page.locator("#summary-log [data-typing]")).toHaveCount(0, { timeout: 15_000 });

  // 测试用的推进按钮（正常情况下这一幕由后端 judge_advance 自己结束）
  await page.locator("#summary-next").click();
  await expect(page.locator("#stage-reflect")).toBeVisible();
  await page.locator("#reflect-input").fill("没有调度时，一个进程可能长期占用 CPU，其他任务无法及时响应。");
  await page.locator("#reflect-submit").click();
  await expect(page.locator("#reflect-next")).toBeVisible();
  await page.locator("#reflect-next").click();

  // 深入思考是最后一个环节，结束后直接进入结束态；课堂讨论界面已移除
  await expect(page.locator("#stage-done")).toBeVisible();
  await expect(page.locator("#stage-discuss")).toHaveCount(0);
  await expect(page.locator("#class-badge")).toHaveText("已结束");
});
