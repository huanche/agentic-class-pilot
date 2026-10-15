// Build first. Runs the actual exported app with deterministic API fixtures.
import { chromium, expect } from '@playwright/test';
import { existsSync } from 'node:fs';
import { resolve, extname } from 'node:path';

const executablePath = ['C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].find(existsSync);
const browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) });
const context = await browser.newContext();
const courseId = '11111111-1111-1111-1111-111111111111';
const platform = { userId: 'student-a', courseId };
const key = `ai-learn.sessionId.platform:student-a:${courseId}.lesson-1`;
const lesson = { lessonId:'lesson-1', title:'恢复课堂', chapter:'第一课', course:'C', summary:'课堂恢复回归', status:'current', week:1, knowledgePointCount:1, segmentCount:1, estimatedMinutes:5, classroomId:'classroom-1', playerUrl:'/player', segments:[] };
const starts = [], requests = [], pageErrors = [];
let phase = 'recap_discussion', renewals = 0;
const state = () => ({ phase, status:'running', updated_at:'2020-01-01T00:00:00Z', stage_elapsed_minutes:2.1, total:0 });
await context.addInitScript(({ key }) => {
  if (!localStorage.getItem(key)) localStorage.setItem(key, 'existing-running');
  if (!sessionStorage.getItem('__launch_token')) sessionStorage.setItem('__launch_token', 'expired');
}, { key });
await context.route('http://localhost:4175/**', async route => {
  const request = route.request(), url = new URL(request.url()), path = url.pathname;
  requests.push(`${request.method()} ${path}`);
  if (path.startsWith('/api/')) {
    if (path.endsWith('/student-workspace')) { renewals++; return route.fulfill({json:{launchToken:'renewed'}}); }
    if (path === '/api/session/start') {
      const body = request.postDataJSON(); starts.push(body);
      if (body.launch_token === 'expired') return route.fulfill({status:401,json:{detail:'expired launch token'}});
      return route.fulfill({json:{...state(),session_id:body.session_id || 'catalog-session',platform}});
    }
    if (path === '/api/session/courses') return route.fulfill({json:[{courseId,name:'C',summary:'恢复课堂',currentWeek:1,lessons:[lesson]}]});
    if (path === '/api/session/lesson') return route.fulfill({json:lesson});
    if (path.endsWith('/state')) return route.fulfill({json:state()});
    if (path.endsWith('/messages')) return route.fulfill({json:{messages:[],total:0}});
    throw new Error(`Unexpected API call: ${request.method()} ${path}`);
  }
  if (path === '/player') return route.fulfill({contentType:'text/html',body:'<p>Local player fixture</p>'});
  const file = resolve('out', path.replace(/^\/app\/?/, '').replace(/^\//, '') || 'index.html');
  if (!file.startsWith(resolve('out')) || !existsSync(file)) return route.fulfill({status:404,body:'missing fixture asset'});
  const types = {'.js':'application/javascript','.css':'text/css','.html':'text/html','.png':'image/png','.woff2':'font/woff2'};
  return route.fulfill({path:file,contentType:types[extname(file)] || 'application/octet-stream'});
});
const classUrl = `http://localhost:4175/app/#/class/${courseId}/lesson-1`;
try {
  let page = await context.newPage();
  page.on('pageerror', e => pageErrors.push(e.message));
  await page.goto(classUrl);
  await expect(page.locator('#stage-summary')).toBeVisible();
  expect(renewals).toBe(1);
  expect(await page.evaluate(key => localStorage.getItem(key), key)).toBe('existing-running');
  await page.reload();
  await expect(page.locator('#stage-summary')).toBeVisible();
  await page.close();
  page = await context.newPage();
  page.on('pageerror', e => pageErrors.push(e.message));
  await page.goto(classUrl);
  await expect(page.locator('#stage-summary')).toBeVisible();
  expect(renewals).toBe(2);
  expect(starts.filter(body => body.lesson_id).every(body => body.session_id === 'existing-running')).toBe(true);
  expect(requests.some(r => r.startsWith('DELETE'))).toBe(false);
  phase = 'guided_learning';
  await page.reload();
  await page.getByRole('button', {name:'开始播放教学视频'}).click();
  await expect(page.locator('#stage-video')).toBeVisible();
  await expect(page.locator('#video-player-slot iframe')).toHaveCount(1);
  const scope = new URL(await page.locator('iframe').getAttribute('src'), classUrl).searchParams.get('resumeKey');
  await page.evaluate(courseId => { location.hash = `#/course/${courseId}`; }, courseId);
  await expect(page.locator('#view-weeks')).toBeVisible();
  await expect(page.locator('#video-player-slot iframe')).toHaveCount(0);
  await page.evaluate(courseId => { location.hash = `#/class/${courseId}/lesson-1`; }, courseId);
  await expect(page.locator('#stage-video')).toBeVisible();
  await expect(page.locator('#video-player-slot iframe')).toHaveCount(1);
  expect(new URL(await page.locator('iframe').getAttribute('src'), classUrl).searchParams.get('resumeKey')).toBe(scope);
  expect(pageErrors).toEqual([]);
  console.log('PASS: actual built app renews expired entry, retains old running session on refresh/new tab, removes player on exit and resumes with the same scope.');
} finally {
  await browser.close();
}
