/* 下课小结必须在结束页可见；覆盖直返、轮询和刷新恢复。 */
import { chromium } from '@playwright/test';
import { readFileSync, existsSync } from 'node:fs';
import assert from 'node:assert/strict';

const chrome = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const browser = await chromium.launch({headless: true, ...(existsSync(chrome) ? {executablePath: chrome} : {})});
try {
  const page = await browser.newPage();
  await page.route('http://ending.test/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/') return route.fulfill({contentType: 'text/html', body: '<body></body>'});
    if (path === '/api.js') return route.fulfill({contentType: 'application/javascript', body: `
      export const fetchSessionState = () => Promise.resolve(window.savedState || {});
    `});
    if (!path.endsWith('.js')) return route.fulfill({status: 204, body: ''});
    const file = path === '/legacyMarkup.js' ? 'src/components/legacyMarkup.js' : 'src/legacy' + path;
    return route.fulfill({contentType: 'application/javascript', body: readFileSync(file, 'utf8')});
  });
  await page.goto('http://ending.test/');
  await page.evaluate(async () => {
    const {legacyMarkup} = await import('/legacyMarkup.js');
    document.body.innerHTML = legacyMarkup;
    const {createStage} = await import('/stage-done.js');
    window.stage = createStage({sessionId: 'summary-session', setStatus() {},
      getKnowledgeCatalog: () => [{no: 1, title: '交换机'}], getLesson: () => ({}),
      getReviewHash: () => '#/review/course/lesson'});
    window.stage.mount();
    window.stage.enter('done', {endingSummary: '这节课学习了交换机，接下来复习连接过程。'});
  });
  assert.match(await page.locator('#stage-done').textContent(), /这节课学习了交换机/,
    '后端已经返回的小结必须显示在结束页，不能只留在隐藏的聊天区');
  await page.evaluate(() => {
    window.stage.enter('done');
    window.stage.receiveMessage('轮询送达的下课总结。');
  });
  assert.match(await page.locator('#stage-done').textContent(), /轮询送达的下课总结/);
  await page.evaluate(() => {
    window.savedState = {hostPhase: 'ending', endingSummary: '恢复后仍可查看的小结。'};
    window.stage.enter('done');
  });
  await page.waitForFunction(() => document.querySelector('#stage-done').textContent.includes('恢复后仍可查看的小结'));
  await page.evaluate(() => window.stage.enter('done', {endingSummary: '<img src=x onerror="window.summaryXss=true">'}));
  assert.equal(await page.locator('#done-summary img').count(), 0);
  assert.equal(await page.evaluate(() => !!window.summaryXss), false);
  console.log('通过：直返、轮询、刷新恢复及文本安全显示。');
} finally {
  await browser.close();
}
