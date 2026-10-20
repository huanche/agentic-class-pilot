import { chromium } from '@playwright/test';
import { readFileSync, existsSync } from 'node:fs';
import assert from 'node:assert/strict';

/* 课后辅导掌握条（工单 02 外壳）：
   - 挂载为聊天面板第一个子节点（在聊天记录上方）；
   - 按学生指定顺序渲染知识点固定编号，当前复习项高亮；
   - 剩余时间 mm:ss 来自服务端 remaining_seconds；
   - 自评与编号一起展示；标题做 HTML 转义。
   复用 tutoring-transition.mjs 的组件测试管线（真浏览器 + 模块直挂）。 */

const chrome = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const browser = await chromium.launch({headless: true, ...(existsSync(chrome) ? {executablePath: chrome} : {})});
try {
  const page = await browser.newPage();
  await page.route('http://tutor.test/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/') {
      return route.fulfill({contentType: 'text/html',
        body: '<head><link rel="stylesheet" href="/globals.css">'
          + '<style>.tm-item{display:block;width:220px;height:26px}.tm-head{display:block;height:20px}</style></head>'
          + '<body><div class="stage stage--chat" id="stage-chat"><div class="chat" id="chat-log"></div><form class="composer" id="composer"></form></div></body>'});
    }
    if (path === '/globals.css') {
      return route.fulfill({contentType: 'text/css',
        body: readFileSync('src/app/globals.css', 'utf8')});
    }
    if (path === '/tutoring-mastery.js') {
      return route.fulfill({contentType: 'application/javascript',
        body: readFileSync('src/legacy/tutoring-mastery.js', 'utf8')});
    }
    return route.fulfill({status: 204, body: ''});
  });
  await page.goto('http://tutor.test/');

  const result = await page.evaluate(async () => {
    const {mountTutoringMastery, renderTutoringMastery} = await import('/tutoring-mastery.js');
    const host = document.getElementById('stage-chat');
    const el = mountTutoringMastery(host);
    renderTutoringMastery(el, {
      knowledge_points: [
        {no: 1, kp_id: 'kp1', title: '调度是什么'},
        {no: 2, kp_id: 'kp2', title: '三级调度'},
        {no: 3, kp_id: 'kp3', title: '<script>alert(1)</script>'},
      ],
      order: [2, 1, 3],
      current_no: 1,
      self_ratings: {2: 2},
      stars: {2: 1},
      rubric: {
        1: '仅接触过概念',
        3: '提示下能做对',
        5: '无提示独立做对未见新题',
      },
      planned_minutes: 15,
      remaining_seconds: 14 * 60 + 5,
    });
    return {
      html: el.innerHTML,
      firstChildIsBar: host.firstElementChild === el,
    };
  });

  assert.ok(result.firstChildIsBar, '掌握条应挂在聊天面板第一个子节点（聊天记录上方）');
  assert.ok(result.html.includes('14:05'), `剩余时间应渲染为 mm:ss：${result.html}`);
  assert.ok(result.html.includes('data-remaining="845"'), `时钟要带服务端锚点：${result.html}`);

  // 每秒走秒：约 1.2 秒后时钟应从 14:05 走到 14:04（不再跟轮询跳 2 秒）
  await assert.doesNotReject(
    () => page.waitForFunction(() => {
      const clock = document.querySelector('.tm-clock');
      return clock && clock.textContent === '14:04';
    }, undefined, {timeout: 4000}),
    '倒计时应每秒走秒');
  assert.ok(result.html.includes('>三级调度<') && result.html.includes('>调度是什么<'),
    `知识点标题要渲染：${result.html}`);
  assert.ok(result.html.indexOf('三级调度') < result.html.indexOf('调度是什么'),
    `学生指定的顺序（先 2 再 1）应体现在渲染顺序：${result.html}`);
  assert.ok(result.html.includes('自评 2★'), `自评要展示：${result.html}`);
  assert.ok(result.html.includes('系统 1★'), `答对后的系统星级要展示：${result.html}`);
  assert.ok(result.html.includes('tm-current'), `当前复习项要高亮：${result.html}`);
  assert.ok(result.html.includes('tm-current"><span class="tm-no">1<'),
    `高亮应落在 current_no=1（正在讲的知识点），不是顺序第一项：${result.html}`);
  assert.ok(!result.html.includes('tm-current"><span class="tm-no">2<'),
    `顺序第一项（2）不应高亮：${result.html}`);
  assert.ok(result.html.includes('&lt;script&gt;') && !result.html.includes('<script>alert'),
    `标题必须 HTML 转义：${result.html}`);

  /* 量规小图标：三态可查看 */
  const icon = page.locator('.tm-rubric').first();
  const rubricText = page.locator('.tm-rubric-text').first();
  await assert.doesNotReject(() => icon.waitFor({state: 'attached'}), '量规图标要存在');
  assert.equal(await icon.getAttribute('aria-label'), '评分标准');
  assert.ok(result.html.includes('5★ 无提示独立做对未见新题'), `量规文本要渲染：${result.html}`);
  assert.equal(await page.evaluate(
    () => getComputedStyle(document.querySelector('.tm-rubric-text')).display),
    'none', '默认隐藏（悬停/聚焦/点击才显示）');

  // 悬停显示/移开隐藏是纯 CSS 行为；无头 Chromium 的 :hover 命中不稳定，
  // 这里断言规则本身存在且默认隐藏（配合上面的 hidden 断言构成契约），
  // 真实浏览器行为由规则保证。
  const hoverRules = await page.evaluate(() => {
    const found = [];
    for (const sheet of document.styleSheets) {
      try {
        for (const rule of sheet.cssRules) {
          if (rule.selectorText && rule.selectorText.includes('.tm-item:hover .tm-rubric-text')) {
            found.push(rule.selectorText + '{display:' + rule.style.display + '}');
          }
        }
      } catch (e) {}
    }
    return found;
  });
  assert.ok(hoverRules.some(r => r.includes('display:block')),
    `悬停显示规则必须存在：${JSON.stringify(hoverRules)}`);

  await page.focus('.tm-rubric');                     // 键盘聚焦显示
  await assert.doesNotReject(() => rubricText.waitFor({state: 'visible'}),
    '键盘聚焦应显示量规');
  await page.evaluate(() => document.activeElement.blur());
  await assert.doesNotReject(() => rubricText.waitFor({state: 'hidden'}),
    '失焦应收起量规');

  await icon.click();                                 // 触屏点击切换
  await assert.doesNotReject(() => rubricText.waitFor({state: 'visible'}),
    '点击应打开量规');
  assert.equal(await icon.getAttribute('aria-expanded'), 'true');
  await icon.click();
  // 点击后鼠标仍悬在图标上（:hover 也会显示），移开后再断言收起——
  // 触屏没有 hover，真实语义就是「点第二下即收起」
  await page.mouse.move(5, 5);
  await assert.doesNotReject(() => rubricText.waitFor({state: 'hidden'}),
    '再点应收起量规');
  assert.equal(await icon.getAttribute('aria-expanded'), 'false');

  console.log('Tutoring mastery bar: order, countdown, self-rating, escaping, rubric icon all rendered.');
} finally {
  await browser.close();
}
