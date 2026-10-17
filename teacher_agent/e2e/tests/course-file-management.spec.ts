import { expect, test, type Page } from '@playwright/test';

test.setTimeout(90000);

async function setup(page: Page) {
  const course = {
    id: 'file-management',
    teacherId: 'teacher',
    title: '课程文件管理',
    status: 'active',
    onboarding: { version: 1, step: 3, completedAt: 1 },
    createdAt: 1,
    updatedAt: 1,
    materials: [
      {
        id: 'source',
        name: '参考资料.txt',
        mimeType: 'text/plain',
        status: 'ready',
        pinned: false,
        createdAt: 1,
        updatedAt: 1,
      },
    ],
    modules: [
      {
        id: 'week',
        title: '第一周',
        workspaceKind: 'week',
        week: 1,
        order: 1,
        pinned: false,
        lessons: [
          {
            id: 'lesson',
            moduleId: 'week',
            title: '第一课时',
            order: 1,
            materialIds: ['source'],
            pinned: false,
            files: [
              {
                id: 'notes',
                lessonId: 'lesson',
                type: 'teaching-activities',
                title: '教学活动',
                content: '原来的活动安排',
                status: 'ready',
                pinned: false,
              },
            ],
          },
          {
            id: 'target',
            moduleId: 'week',
            title: '第二课时',
            order: 2,
            materialIds: [] as string[],
            pinned: false,
            files: [] as Array<{
              id: string;
              lessonId: string;
              type: string;
              title: string;
              content: string;
              status: string;
              pinned: boolean;
            }>,
          },
        ],
      },
    ],
  };
  const artifacts = [
    {
      id: 'artifact',
      title: '课程讲稿',
      content: '原讲稿',
      htmlContent: '<h1>原讲稿</h1>',
      type: 'narration',
      scope: { type: 'lesson', lessonId: 'lesson' },
      status: 'review',
      pinned: false,
    },
  ];
  const requests: Array<{ path: string; body: Record<string, unknown> }> = [];
  const failures = { metadata: false, deletion: false };
  await page.route('**/api/course-space**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    const method = route.request().method();
    if (path.endsWith('/management')) {
      const body = route.request().postDataJSON();
      requests.push({ path, body });
      if (failures.metadata)
        return route.fulfill({ status: 409, json: { success: false, error: '保存失败，请重试' } });
      const item =
        body.kind === 'artifacts'
          ? artifacts.find((item) => item.id === body.id)
          : body.kind === 'materials'
            ? course.materials.find((item) => item.id === body.id)
            : body.kind === 'modules'
              ? course.modules.find((item) => item.id === body.id)
              : body.kind === 'lessons'
                ? course.modules[0].lessons.find((item) => item.id === body.id)
                : course.modules[0].lessons
                    .flatMap((lesson) => lesson.files)
                    .find((item) => item.id === body.id);
      if (item)
        Object.assign(
          item,
          body.title !== undefined
            ? { [body.kind === 'materials' ? 'name' : 'title']: body.title }
            : {},
          body.pinned !== undefined ? { pinned: body.pinned } : {},
        );
    } else if (path.endsWith('/tree') && method === 'POST') {
      const body = route.request().postDataJSON();
      requests.push({ path, body });
      const file = course.modules[0].lessons
        .flatMap((lesson) => lesson.files)
        .find((item) => item.id === body.itemId);
      if (file && body.action === 'move-item') {
        course.modules[0].lessons.forEach((lesson) => {
          lesson.files = lesson.files.filter((item) => item.id !== file.id);
        });
        course.modules[0].lessons
          .find((lesson) => lesson.id === body.targetLessonId)!
          .files.push({ ...file, lessonId: body.targetLessonId });
      }
    } else if (method === 'DELETE') {
      if (failures.deletion)
        return route.fulfill({ status: 409, json: { success: false, error: '文件暂时不能删除' } });
      const id = path.split('/').at(-1);
      course.modules[0].lessons.forEach((lesson) => {
        lesson.files = lesson.files.filter((item) => item.id !== id);
      });
      const index = artifacts.findIndex((item) => item.id === id);
      if (index >= 0) artifacts.splice(index, 1);
    } else if (method === 'PUT') {
      const old = course.materials[0];
      const material = { ...old, id: 'replacement', name: '编辑后的资料.txt', status: 'uploaded' };
      course.materials = [material];
      course.modules[0].lessons.forEach((lesson) => {
        lesson.materialIds = lesson.materialIds.map((id) => (id === old.id ? material.id : id));
      });
      return route.fulfill({ json: { success: true, material } });
    } else if (method === 'PATCH') {
      const body = route.request().postDataJSON();
      requests.push({ path, body });
      const id = path.split('/').at(-1);
      const item =
        artifacts.find((item) => item.id === id) ??
        course.modules[0].lessons.flatMap((lesson) => lesson.files).find((item) => item.id === id);
      if (item && typeof body.content === 'string') item.content = body.content;
    }
    return route.fulfill({
      json: {
        success: true,
        course,
        courses: [course],
        artifacts,
        jobs: [],
        sessions: [],
        events: [],
      },
    });
  });
  await page.goto('/course-space?workspace=file-management');
  await expect(page.getByRole('button', { name: '展开“第一课时”', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '展开“第一课时”', exact: true }).click();
  return { course, artifacts, requests, failures };
}

const row = (page: Page, id: string) => page.locator(`[data-file-location="${id}"]`).last();
const menu = async (page: Page, id: string, action: string) => {
  await row(page, id).getByRole('button', { name: /^管理/ }).click();
  await page.getByRole('menuitem', { name: action, exact: true }).click();
};

test('rename, pin, reload, reveal, edit and move a lesson file from visible menus', async ({
  page,
}) => {
  const { requests } = await setup(page);
  await menu(page, 'notes', '重命名');
  await page.getByRole('textbox', { name: '名称', exact: true }).fill('课堂实践安排');
  await page.getByRole('textbox', { name: '名称', exact: true }).press('Enter');
  await expect(row(page, 'notes')).toContainText('课堂实践安排');
  await menu(page, 'notes', '置顶');
  await expect(page.getByRole('region', { name: '置顶项目' })).toContainText('课堂实践安排');
  await page.reload();
  const pinned = page.getByRole('region', { name: '置顶项目' });
  await expect(pinned).toContainText('课堂实践安排');
  await pinned.getByRole('button', { name: '管理“课堂实践安排”' }).click();
  await page.getByRole('menuitem', { name: '打开文件位置' }).click();
  await expect(
    row(page, 'notes').getByRole('button', { name: /课堂实践安排.*已审核/ }),
  ).toBeFocused();
  await menu(page, 'notes', '编辑');
  await page.getByRole('textbox', { name: '编辑文件内容' }).fill('教师更新后的实践任务');
  await page.getByRole('button', { name: '保存修改', exact: true }).click();
  await expect
    .poll(
      () => requests.find((request) => request.path.endsWith('/lesson-files/notes'))?.body.content,
    )
    .toBe('教师更新后的实践任务');
  await menu(page, 'notes', '移动到…');
  await page.getByLabel('目标课时', { exact: true }).selectOption('target');
  await page.getByRole('button', { name: '确认移动', exact: true }).click();
  await expect(
    page.locator('[data-lesson-folder="target"] [data-file-location="notes"]'),
  ).toBeVisible();
  await menu(page, 'notes', '取消置顶');
  await expect(pinned).toHaveCount(0);
});

test('context menus manage folders and artifacts; failed writes remain visible and deletions require confirmation', async ({
  page,
}) => {
  const { failures, requests } = await setup(page);
  await row(page, 'week')
    .getByRole('button', { name: '第一周', exact: true })
    .click({ button: 'right' });
  await page.getByRole('menuitem', { name: '重命名' }).click();
  await page.getByRole('textbox', { name: '名称', exact: true }).fill('导论与实践');
  await page.getByRole('button', { name: '保存名称' }).click();
  await expect(row(page, 'week')).toContainText('导论与实践');
  await menu(page, 'week', '置顶');
  await expect(page.getByRole('region', { name: '置顶项目' })).toContainText('导论与实践');
  failures.metadata = true;
  await menu(page, 'artifact', '重命名');
  await page.getByRole('textbox', { name: '名称', exact: true }).fill('失败的名称');
  await page.getByRole('button', { name: '保存名称' }).click();
  await expect(page.getByRole('dialog')).toContainText('保存失败，请重试');
  await page.getByRole('button', { name: '取消', exact: true }).click();
  await expect(row(page, 'artifact')).toContainText('课程讲稿');
  await menu(page, 'artifact', '编辑');
  await page.getByRole('textbox', { name: '编辑文件内容' }).fill('修改后的讲稿');
  await page.getByRole('button', { name: '保存修改' }).click();
  await expect
    .poll(
      () => requests.find((request) => request.path.endsWith('/artifacts/artifact'))?.body.content,
    )
    .toBe('修改后的讲稿');
  await menu(page, 'artifact', '删除');
  await page.getByRole('button', { name: '保留当前状态' }).click();
  await expect(row(page, 'artifact')).toBeVisible();
  failures.deletion = true;
  await menu(page, 'artifact', '删除');
  await page.getByRole('button', { name: '确认删除' }).click();
  await expect(page.getByRole('alertdialog')).toContainText('文件暂时不能删除');
  failures.deletion = false;
  await page.getByRole('button', { name: '确认删除' }).click();
  await expect(page.getByRole('alertdialog')).toHaveCount(0);
  await expect(row(page, 'artifact')).toHaveCount(0);
});

test('source editing downloads the original and replaces it without losing its folder or pin', async ({
  page,
}) => {
  const { course } = await setup(page);
  await menu(page, 'source', '置顶');
  await menu(page, 'source', '编辑');
  await expect(page.getByRole('link', { name: '下载原始文件' })).toHaveAttribute(
    'href',
    /materials\/source$/,
  );
  await page.getByLabel('选择编辑后的文件', { exact: true }).setInputFiles({
    name: '编辑后的资料.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('new material'),
  });
  await page.getByRole('button', { name: '替换源文件', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.getByRole('region', { name: '置顶项目' })).toContainText('编辑后的资料.txt');
  expect(course.modules[0].lessons[0].materialIds).toEqual(['replacement']);
  await page.setViewportSize({ width: 1080, height: 900 });
  await row(page, 'replacement').getByRole('button', { name: /^管理/ }).click();
  await expect(page.getByRole('menuitem', { name: '打开文件位置' })).toBeInViewport();
  await page.screenshot({ path: 'test-results/course-file-management-menu.png', fullPage: true });
  await page.keyboard.press('Escape');
  await expect(page.getByRole('menu')).toHaveCount(0);
});

test('interactive courseware opens the embedded editor and published files explain the edit restriction', async ({
  page,
}) => {
  const { artifacts } = await setup(page);
  Object.assign(artifacts[0], { classroomUrl: '/classroom/editor-fixture' });
  await page.route('**/classroom/editor-fixture**', (route) =>
    route.fulfill({ contentType: 'text/html', body: '<h1>课件编辑器</h1>' }),
  );
  await page.reload();
  await page.getByRole('button', { name: '展开“第一课时”', exact: true }).click();
  await menu(page, 'artifact', '编辑');
  await expect(page.locator('iframe[title="课程讲稿"]')).toHaveAttribute(
    'src',
    '/classroom/editor-fixture?embedded=course-workspace',
  );
  Object.assign(artifacts[0], { status: 'published', classPublicationId: 'CLS-test' });
  await page.reload();
  await page.getByRole('button', { name: '展开“第一课时”', exact: true }).click();
  await row(page, 'artifact').getByRole('button', { name: /^管理/ }).click();
  await expect(page.getByRole('menuitem', { name: '编辑（请先取消发布）' })).toBeDisabled();
  await expect(page.getByRole('menuitem', { name: '重命名' })).toBeEnabled();
  await expect(page.getByRole('menuitem', { name: '置顶', exact: true })).toBeEnabled();
});

test('renamed filenames are displayed as text in empty file and legacy artifact previews', async ({
  page,
}) => {
  const { course, artifacts } = await setup(page);
  course.modules[0].lessons[0].files[0].content = '';
  artifacts[0].htmlContent = '';
  await page.reload();
  await page.getByRole('button', { name: '展开“第一课时”', exact: true }).click();
  const filename = '<img src=x onerror="alert(1)">';
  for (const id of ['notes', 'artifact']) {
    await menu(page, id, '重命名');
    await page.getByRole('textbox', { name: '名称', exact: true }).fill(filename);
    await page.getByRole('button', { name: '保存名称' }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await row(page, id).getByRole('button').first().click();
    const preview = page.frameLocator('iframe').first();
    await expect(preview.getByRole('heading', { name: filename, exact: true })).toBeVisible();
    await expect(preview.locator('img')).toHaveCount(0);
  }
});
