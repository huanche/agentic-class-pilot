import { chromium } from '@playwright/test';
import { readFileSync, existsSync } from 'node:fs';
import assert from 'node:assert/strict';

const chrome = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const browser = await chromium.launch({headless: true, ...(existsSync(chrome) ? {executablePath: chrome} : {})});
try {
  const page = await browser.newPage();
  await page.route('http://replay.test/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/') return route.fulfill({contentType: 'text/html', body: '<body></body>'});
    if (path === '/api.js') return route.fulfill({contentType: 'application/javascript', body: `
      export const beginSession = () => Promise.resolve({});
      export const sendMessage = beginSession;
      export const notifyMediaDone = () => {window.notifications++; return Promise.resolve({});};
      export const fetchLessonVideo = () => window.deferVideo ? new Promise(r => window.resolveVideo = r) : Promise.resolve({url:'video'});
    `});
    if (!path.endsWith('.js')) return route.fulfill({status:204, body:''});
    const file = path === '/legacyMarkup.js' ? 'src/components/legacyMarkup.js' : 'src/legacy' + path;
    return route.fulfill({contentType:'application/javascript', body:readFileSync(file,'utf8')});
  });
  await page.goto('http://replay.test/');
  await page.evaluate(async () => {
    const {legacyMarkup} = await import('/legacyMarkup.js');
    document.body.innerHTML = legacyMarkup;
    const {registerVideoPlayer} = await import('/video-player.js');
    const {createStage} = await import('/stage-class.js');
    window.notifications = 0;
    window.mounts = 0;
    window.destroyed = 0;
    registerVideoPlayer({mount(slot, ctx) {
      window.mounts++;
      window.playerContext = ctx;
      slot.textContent = 'shared player';
      return () => {window.destroyed++;};
    }});
    window.stage = createStage({lessonId:'lesson-selected',sessionId:'finished-session',
      getLesson:()=>({classroomId:'class-selected',segments:[]}),setStatus:()=>{},
      getReviewHash:()=> '#/review/course/lesson-selected',toast:()=>{},
      replySeenByPoll:()=>false,applyServerTurn:()=>{}});
    stage.mount();
    stage.startReplay();
  });
  await page.waitForFunction(() => window.mounts === 1);
  assert.equal(await page.locator('#btn-skip-video').getAttribute('hidden'), '');
  assert.equal(await page.locator('#btn-exit-replay').getAttribute('hidden'), null);
  assert.equal(await page.evaluate(() => playerContext.classroomId), 'class-selected');
  await page.evaluate(() => playerContext.onEnded('scene', 'event'));
  assert.equal(await page.evaluate(() => notifications), 0);
  await page.evaluate(() => document.getElementById('btn-exit-replay').click());
  assert.equal(new URL(page.url()).hash, '#/review/course/lesson-selected');
  assert.equal(await page.evaluate(() => destroyed), 1);
  await page.evaluate(() => {deferVideo = true; stage.startReplay(); stage.leave(); resolveVideo({});});
  await page.evaluate(() => Promise.resolve());
  assert.equal(await page.evaluate(() => mounts), 1, 'late response must not remount after leaving');
  console.log('Replay: shared player, selected lesson, no progress mutation, exit cleanup and late-response guard passed.');
} finally {
  await browser.close();
}
