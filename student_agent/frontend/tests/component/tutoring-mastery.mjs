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
        body: '<body><div class="stage stage--chat" id="stage-chat"><div class="chat" id="chat-log"></div><form class="composer" id="composer"></form></div></body>'});
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
      self_ratings: {2: 2},
      stars: {2: 1},
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
  assert.ok(result.html.includes('>三级调度<') && result.html.includes('>调度是什么<'),
    `知识点标题要渲染：${result.html}`);
  assert.ok(result.html.indexOf('三级调度') < result.html.indexOf('调度是什么'),
    `学生指定的顺序（先 2 再 1）应体现在渲染顺序：${result.html}`);
  assert.ok(result.html.includes('自评 2★'), `自评要展示：${result.html}`);
  assert.ok(result.html.includes('系统 1★'), `答对后的系统星级要展示：${result.html}`);
  assert.ok(result.html.includes('tm-current'), `当前复习项要高亮：${result.html}`);
  assert.ok(result.html.includes('&lt;script&gt;') && !result.html.includes('<script>alert'),
    `标题必须 HTML 转义：${result.html}`);

  console.log('Tutoring mastery bar: order, countdown, self-rating, escaping all rendered.');
} finally {
  await browser.close();
}
