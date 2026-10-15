// Run against the local teacher server: node tests/browser/student-bugfixes.mjs
import { chromium, expect } from '@playwright/test';
import { existsSync } from 'node:fs';

const executablePath = ['C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].find(existsSync);
const browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) });
const base = process.env.STUDENT_PLAYER_TEST_URL || 'http://localhost:3004';
const stageId = 'student-bugfix-regression', scope = 'test-student-12345678', now = Date.now();
const cursorKey = `maic:device:playback-cursor:student:${scope}:${stageId}`;
const slide = (id, order) => ({
  id, stageId, type:'slide', title:id, order, createdAt:now, updatedAt:now,
  content:{type:'slide',canvas:{elements:[],background:{color:'#ffffff'}}},
  actions:[{id:id+'-first',type:'speech',text:'第一句。'}, {id:id+'-second',type:'speech',text:'续播目标句。'.repeat(100)}],
});
const question = (id, question) => ({id,type:'single',question,options:[{label:'正常退出',value:'A'},{label:'无限循环',value:'B'}],answer:['A'],analysis:'测试解析'});
const classroom = {
  stage:{id:stageId,name:'学生故障回归',language:'zh-CN',createdAt:now,updatedAt:now,dslVersion:'0.1.0'},
  scenes:[slide('slide-1',0),slide('slide-2',1),{
    id:'quiz',stageId,type:'quiz',title:'练习',order:2,createdAt:now,updatedAt:now,
    content:{type:'quiz',questions:[
      question('q1','第一题：\n```c\nint main() {\n  return 0;\n}\n```'),
      question('q2','第二题：程序运行结果'), question('q3','第三题：程序运行结果'),
    ]},
  }],
};
const errors = [];
async function openAt(sceneId, actionIndex) {
  const context = await browser.newContext();
  await context.route('**/api/classroom?*', route => route.fulfill({json:{success:true,classroom}}));
  await context.route('**/api/server-providers', route => route.fulfill({json:{providers:[]}}));
  await context.addInitScript(({cursorKey,sceneId,actionIndex}) => {
    localStorage.setItem('maic:account:settings-storage', JSON.stringify({state:{ttsEnabled:false,selectedAgentIds:[],autoConfigApplied:true,locale:'zh-CN'},version:2}));
    if (!localStorage.getItem(cursorKey)) localStorage.setItem(cursorKey,JSON.stringify({sceneId,actionIndex,updatedAt:'2020-01-01T00:00:00Z'}));
    Object.defineProperty(window,'speechSynthesis',{value:undefined,configurable:true});
  }, {cursorKey,sceneId,actionIndex});
  const page = await context.newPage();
  // Install clock hooks before the app creates timers, so clearInterval can
  // clear the matching timer implementation when a question expires.
  await page.clock.setFixedTime(Date.now());
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(`${base}/classroom-player/${stageId}?embedded=player&resumeKey=${scope}`);
  return {context,page};
}
try {
  const lecture = await openAt('slide-2',1);
  await expect.poll(() => lecture.page.evaluate(key => JSON.parse(localStorage.getItem(key)).updatedAt, cursorKey), {timeout:120000}).not.toBe('2020-01-01T00:00:00Z');
  expect(await lecture.page.evaluate(key => {
    const cursor=JSON.parse(localStorage.getItem(key)); return [cursor.sceneId,cursor.actionIndex];
  }, cursorKey)).toEqual(['slide-2',1]);
  await lecture.context.close();

  const {context,page} = await openAt('quiz',0);
  const code = page.locator('code').filter({hasText:'int main'});
  await expect(code).toBeVisible({timeout:60000});
  await expect(code).toHaveText('int main() {\n  return 0;\n}\n');
  expect(await code.evaluate(element => getComputedStyle(element).whiteSpace)).toBe('pre');
  await expect(page.getByText(/^本页 /)).toHaveCount(0);
  await page.getByText('正常退出',{exact:true}).click();
  const clockStart = Date.now();
  await page.clock.setFixedTime(clockStart + 40000);
  await page.waitForTimeout(1200);
  await expect(code).toBeVisible();
  await expect(page.getByText('第二题：程序运行结果',{exact:true})).toHaveCount(0);
  await page.clock.setFixedTime(clockStart + 61000);
  await expect(page.getByText('第二题：程序运行结果',{exact:true})).toBeVisible();
  await page.waitForTimeout(1500);
  await expect(page.getByText('第三题：程序运行结果',{exact:true})).toHaveCount(0);
  // A new tab restores the quiz page rather than replaying the first slide.
  const fresh = await context.newPage();
  await fresh.goto(page.url());
  await expect(fresh.locator('code').filter({hasText:'int main'})).toBeVisible({timeout:60000});
  expect(errors).toEqual([]);
  console.log('PASS: saved page/sentence resume; quiz page restore; code layout; no early/duplicate timeout; existing one-minute timeout preserved.');
} finally {
  await browser.close();
}
