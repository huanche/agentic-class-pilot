import { expect, test, type Page } from '@playwright/test';

test.setTimeout(90000);
const courseId = 'review-e2e';
const planId = 'review-plan';
const endpoint = `/api/course-space/${courseId}/lesson-files/draft`;

async function openReview(page: Page, lessonIds = ['l1']) {
  await page.addInitScript(({ planId, lessonIds }) => {
    sessionStorage.setItem(`teacher-plan:${planId}`, JSON.stringify({
      id: planId, kind: 'create-lesson-files', title: '生成课时目标',
      summary: '根据课程材料生成课时目标', requiresConfirmation: true, status: 'planned', steps: [],
      action: { type: 'create-lesson-files', lessonIds, fileTypes: ['lesson-objectives'], populateContent: true, instruction: '生成课时目标' },
    }));
  }, { planId, lessonIds });
  await page.goto(`/course-space/${courseId}/prepare?draft=${planId}`);
  await expect(page.getByRole('button', { name: '确认并生成草稿' })).toBeVisible();
}

function draft(lessonId: string) {
  return {
    success: true, lessonId, lessonTitle: `课时 ${lessonId}`, baseVersion: 'a'.repeat(64),
    drafts: [{ type: 'lesson-objectives', title: '课时目标', content: `草稿 ${lessonId}` }],
  };
}

test('single lesson waits for confirmation and saves only reviewed edits', async ({ page }) => {
  const posts: unknown[] = [];
  const patches: Array<{ lessons: Array<{ drafts: Array<{ content: string }> }> }> = [];
  await page.route(`**${endpoint}`, async (route) => {
    if (route.request().method() === 'POST') {
      posts.push(route.request().postDataJSON());
      await route.fulfill({ json: draft('l1') });
    } else {
      patches.push(route.request().postDataJSON());
      await route.fulfill({ json: { success: true } });
    }
  });
  await openReview(page);
  expect(posts).toHaveLength(0);
  await page.getByRole('button', { name: '确认并生成草稿' }).click();
  await expect(page.getByRole('textbox')).toHaveValue('草稿 l1');
  expect(patches).toHaveLength(0);
  await page.getByRole('textbox').fill('教师审核后的目标');
  await page.getByRole('button', { name: '审核通过并统一保存' }).click();
  await expect(page.getByRole('heading', { name: '已审核保存 1 个课时' })).toBeVisible();
  expect(patches[0].lessons[0].drafts[0].content).toBe('教师审核后的目标');
  await expect(page.getByRole('link', { name: '预览 课时 l1' })).toBeVisible();
  expect(await page.evaluate((id) => sessionStorage.getItem(`teacher-plan:${id}`), planId)).toBeNull();
});

test('batch review sends all lessons in one save request', async ({ page }) => {
  const patches: Array<{ lessons: Array<{ lessonId: string }> }> = [];
  await page.route(`**${endpoint}`, async (route) => {
    const body = route.request().postDataJSON();
    if (route.request().method() === 'POST') await route.fulfill({ json: draft(body.lessonId) });
    else { patches.push(body); await route.fulfill({ json: { success: true } }); }
  });
  await openReview(page, ['l1', 'l2']);
  await page.getByRole('button', { name: '确认并生成草稿' }).click();
  await expect(page.getByRole('textbox')).toHaveCount(2);
  expect(patches).toHaveLength(0);
  await page.getByRole('button', { name: '审核通过并统一保存' }).click();
  await expect(page.getByRole('heading', { name: '已审核保存 2 个课时' })).toBeVisible();
  expect(patches).toHaveLength(1);
  expect(patches[0].lessons.map((lesson) => lesson.lessonId)).toEqual(['l1', 'l2']);
  await expect(page.getByRole('link', { name: /预览 课时/ })).toHaveCount(2);
});

test('partial generation cannot save; retry preserves successful teacher edits', async ({ page }) => {
  const requests: string[] = [];
  let fail = true;
  let saves = 0;
  await page.route(`**${endpoint}`, async (route) => {
    const body = route.request().postDataJSON();
    if (route.request().method() === 'PATCH') { saves++; await route.fulfill({ json: { success: true } }); return; }
    requests.push(body.lessonId);
    if (body.lessonId === 'l2' && fail) {
      fail = false;
      await route.fulfill({ status: 500, json: { success: false, error: '模型暂时不可用' } });
    } else await route.fulfill({ json: draft(body.lessonId) });
  });
  await openReview(page, ['l1', 'l2']);
  await page.getByRole('button', { name: '确认并生成草稿' }).click();
  await expect(page.getByRole('alert').filter({ hasText: '模型暂时不可用' })).toBeVisible();
  await expect(page.getByRole('button', { name: '审核通过并统一保存' })).toBeDisabled();
  expect(saves).toBe(0);
  await page.getByRole('textbox').fill('保留我的修改');
  await page.getByRole('button', { name: '重试失败课时（保留已编辑草稿）' }).click();
  await expect(page.getByRole('textbox')).toHaveCount(2);
  await expect(page.getByRole('textbox').first()).toHaveValue('保留我的修改');
  expect(requests).toEqual(['l1', 'l2', 'l2']);
  await expect(page.getByRole('button', { name: '审核通过并统一保存' })).toBeEnabled();
});

test('cancel review never sends a write request', async ({ page }) => {
  let saves = 0;
  await page.route(`**${endpoint}`, async (route) => {
    if (route.request().method() === 'PATCH') saves++;
    await route.fulfill({ json: draft('l1') });
  });
  await page.route('**/api/course-space?**', (route) => route.fulfill({ json: { success: true, courses: [] } }));
  await openReview(page);
  await page.getByRole('button', { name: '确认并生成草稿' }).click();
  await expect(page.getByRole('textbox')).toBeVisible();
  await page.getByRole('button', { name: '取消，不保存' }).click();
  await expect(page).toHaveURL(new RegExp(`/course-space\\?workspace=${courseId}`));
  expect(saves).toBe(0);
});

test('concurrent edit conflict leaves drafts editable without showing saved success', async ({ page }) => {
  await page.route(`**${endpoint}`, async (route) => {
    if (route.request().method() === 'POST') await route.fulfill({ json: draft('l1') });
    else await route.fulfill({ status: 409, json: { success: false, error: '原文件已变化，请重新生成草稿后审核' } });
  });
  await openReview(page);
  await page.getByRole('button', { name: '确认并生成草稿' }).click();
  await expect(page.getByRole('textbox')).toBeVisible();
  await page.getByRole('button', { name: '审核通过并统一保存' }).click();
  await expect(page.getByRole('alert').filter({ hasText: '原文件已变化' })).toBeVisible();
  await expect(page.getByRole('textbox')).toBeEnabled();
  await expect(page.getByRole('heading', { name: /已审核保存/ })).toHaveCount(0);
});