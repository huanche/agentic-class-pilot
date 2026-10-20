import { chromium } from '@playwright/test';
import { readFileSync, existsSync } from 'node:fs';
import assert from 'node:assert/strict';

/* 视频播完的过渡态文案：
   - 下一幕是 tutoring（开关开启）→ 文案说「正在进入课后辅导」，不再是"等老师准备"；
   - 下一幕是 recap_discussion（开关关闭）→ 维持原有文案，一字不改。
   复用 replay.mjs 的组件测试管线：stub 掉 api.js，真挂 stage-class.js。 */

const chrome = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const browser = await chromium.launch({headless: true, ...(existsSync(chrome) ? {executablePath: chrome} : {})});
try {
  const page = await browser.newPage();
  await page.route('http://tutor.test/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/') return route.fulfill({contentType: 'text/html', body: '<body></body>'});
    if (path === '/api.js') return route.fulfill({contentType: 'application/javascript', body: `
      export const beginSession = () => Promise.resolve({message: {text: ''}, hostPhase: 'guided_learning', total: 0});
      export const sendMessage = beginSession;
      export const notifyMediaDone = () => {window.notifications++; return Promise.resolve({});};
      export const fetchLessonVideo = () => Promise.resolve({url: 'video'});
    `});
    if (!path.endsWith('.js')) return route.fulfill({status: 204, body: ''});
    const file = path === '/legacyMarkup.js' ? 'src/components/legacyMarkup.js' : 'src/legacy' + path;
    return route.fulfill({contentType: 'application/javascript', body: readFileSync(file, 'utf8')});
  });
  await page.goto('http://tutor.test/');
  await page.evaluate(async () => {
    const {legacyMarkup} = await import('/legacyMarkup.js');
    document.body.innerHTML = legacyMarkup;
    const {registerVideoPlayer} = await import('/video-player.js');
    const {createStage} = await import('/stage-class.js');
    window.notifications = 0;
    window.playerContexts = [];
    registerVideoPlayer({mount(slot, ctx) {
      window.playerContexts.push(ctx);
      slot.textContent = 'player';
      return () => {};
    }});
    window.stage = createStage({
      lessonId: 'lesson-x', sessionId: 'session-x',
      getLesson: () => ({classroomId: 'c1', segments: []}),
      setStatus: () => {},
      showStage: () => {},
      getPhase: () => 'guided_learning',
      getNextStage: () => window.nextStage,
      getReviewHash: () => '#/review/c/l', toast: () => {},
      replySeenByPoll: () => false, applyServerTurn: () => {},
    });
    stage.mount();
  });

  async function transitionCopyFor(nextStage) {
    await page.evaluate((ns) => {
      window.nextStage = ns;
      window.notifications = 0;
      window.playerContexts.length = 0;
    }, nextStage);
    // 首次要先「开始上课」才会挂出「开始播放教学视频」按钮。视频播完后该
    // 操作行会被清掉（新契约：播完不再常驻），第二个场景先 reset 课堂模块
    // 恢复 introDone，再走一遍开课挂按钮
    const hasIntro = await page.evaluate(
      () => document.querySelectorAll('#chat-log .chat-action button').length > 0);
    if (!hasIntro) {
      await page.evaluate(() => {
        if (window.stage && window.stage.reset) window.stage.reset();
        // markup 里 btn-start 初始 disabled（真实流程由 openLessonRoute 解锁），
        // 组件测试里直接解锁后点击
        const btn = document.getElementById('btn-start');
        btn.disabled = false;
        btn.click();
      });
      await page.waitForFunction(
        () => document.querySelectorAll('#chat-log .chat-action button').length === 1);
    }
    // 裸 markup 没有 CSS（元素零尺寸），用 attach 判断 + DOM click，与 replay.mjs 同法。
    await page.evaluate(
      () => document.querySelector('#chat-log .chat-action button').click());
    await page.waitForFunction(() => window.playerContexts.length === 1);
    await page.evaluate(() => window.playerContexts[0].onEnded('scene', 'event'));
    await page.waitForFunction(() => window.notifications === 1);
    return page.evaluate(() => ({
      copy: document.getElementById('video-player-status').textContent,
    }));
  }

  const tutoring = await transitionCopyFor('tutoring');
  assert.ok(tutoring.copy.includes('课后辅导'), `过渡文案应提到课后辅导：${tutoring.copy}`);
  assert.ok(!tutoring.copy.includes('准备下一环节'), `辅导过渡不应再说"等老师准备下一环节"：${tutoring.copy}`);

  const legacy = await transitionCopyFor('recap_discussion');
  assert.ok(legacy.copy.includes('老师'), `开关关闭应维持原有"等老师准备"文案：${legacy.copy}`);
  assert.ok(!legacy.copy.includes('课后辅导'), `开关关闭不应出现辅导文案：${legacy.copy}`);

  console.log('Tutoring transition copy: tutoring path replaces the waiting text, legacy path unchanged.');
} finally {
  await browser.close();
}
