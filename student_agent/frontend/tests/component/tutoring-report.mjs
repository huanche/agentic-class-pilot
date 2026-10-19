import { chromium } from '@playwright/test';
import { readFileSync, existsSync } from 'node:fs';
import assert from 'node:assert/strict';

/* 课后辅导反馈卡（工单 05）：渲染最新版反馈的学生视角——
   版本号、用时/答题统计、知识点系统星+自评+依据条数、
   未完成检测、建议；教师摘要不出现在学生端。 */

const chrome = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const browser = await chromium.launch({headless: true, ...(existsSync(chrome) ? {executablePath: chrome} : {})});
try {
  const page = await browser.newPage();
  await page.route('http://tutor.test/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/') {
      return route.fulfill({contentType: 'text/html',
        body: '<body><div id="box"></div></body>'});
    }
    if (path === '/ui.js' || path === '/tutoring-report.js') {
      return route.fulfill({contentType: 'application/javascript',
        body: readFileSync('src/legacy' + path, 'utf8')});
    }
    return route.fulfill({status: 204, body: ''});
  });
  await page.goto('http://tutor.test/');

  const out = await page.evaluate(async () => {
    const {renderTutoringReportCard} = await import('/tutoring-report.js');
    const box = document.getElementById('box');
    renderTutoringReportCard(box, {
      version: 1,
      payload: {
        schema: 'tutoring-feedback/1',
        actual_minutes: 14, planned_minutes: 15,
        asked_questions: 3, stats: {correct: 2, wrong: 1},
        knowledge_points: [
          {no: 1, kp_id: 'kp1', title: '调度是什么', system_stars: 2,
           self_rating: 4, evidence: ['辅导检测题答对（无提示独立作答）', '另一条']},
          {no: 2, kp_id: 'kp2', title: '<img src=x>三级调度', system_stars: 0,
           self_rating: null, evidence: []},
        ],
        unfinished_question: '小检测：请用自己的话说说「三级调度」',
        advice: '课后优先复习：三级调度',
      },
      teacher_summary: '教师视角摘要不应出现在学生端',
    });
    const html = box.innerHTML;
    const text = box.innerText;
    renderTutoringReportCard(box, null);
    return {html, text, cleared: box.children.length === 0};
  });

  assert.ok(out.text.includes('第 1 版'), `版本号要展示：${out.text}`);
  assert.ok(out.text.includes('复习约 14 分钟（计划 15）'), `用时：${out.text}`);
  assert.ok(out.text.includes('出题 3 道 · 答对 2 · 答错 1'), `统计：${out.text}`);
  assert.ok(out.text.includes('系统 2★') && out.text.includes('自评 4★'), `星级：${out.text}`);
  assert.ok(out.text.includes('依据 2 条'), `证据条数：${out.text}`);
  assert.ok(out.text.includes('未检测'), `0 星显示未检测：${out.text}`);
  assert.ok(out.text.includes('未完成检测：小检测'), `未完成检测：${out.text}`);
  assert.ok(out.text.includes('课后优先复习'), `建议：${out.text}`);
  assert.ok(out.html.includes('&lt;img src=x&gt;'), `标题要转义：${out.html}`);
  assert.ok(!out.text.includes('教师视角'), `教师摘要不得出现在学生端：${out.text}`);
  assert.ok(out.cleared, 'report 为 null 时应清空容器');

  console.log('Tutoring report card: version, stats, stars, evidence, advice, escaping all rendered.');
} finally {
  await browser.close();
}
