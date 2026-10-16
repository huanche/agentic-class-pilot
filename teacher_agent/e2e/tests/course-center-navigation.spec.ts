import { test, expect } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  const courses = ['a', 'b'].map((id) => ({
    id: `course-${id}`,
    teacherId: 'teacher-001',
    title: `回归课程 ${id.toUpperCase()}`,
    status: 'draft',
    materials: [],
    createdAt: 1,
    updatedAt: 1,
    onboarding: { version: 1, step: 3, completedAt: 1 },
    modules: [
      {
        id: `module-${id}`,
        title: '测试模块',
        order: 1,
        lessons: [
          {
            id: `lesson-${id}`,
            moduleId: `module-${id}`,
            title: '测试课时',
            order: 1,
            materialIds: [],
          },
        ],
      },
    ],
  }));
  await page.route('**/api/course-space**', async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    const id = pathname.split('/')[3];
    if (route.request().method() === 'DELETE') {
      const index = courses.findIndex((course) => course.id === id);
      if (index >= 0) courses.splice(index, 1);
      return route.fulfill({ json: { success: true, deleted: true } });
    }
    return route.fulfill({
      json: {
        success: true,
        courses,
        course: courses.find((course) => course.id === id),
        jobs: [],
        artifacts: [],
        sessions: [],
        events: [],
      },
    });
  });
});

for (const button of ['返回课程中心', '课程中心']) {
  test(`${button} switches the existing workspace page back to the center`, async ({ page }) => {
    await page.goto('/course-space?workspace=course-a');
    await expect(page.getByRole('button', { name: button, exact: true })).toBeVisible();
    await page.getByRole('button', { name: button, exact: true }).click();
    await expect(page).toHaveURL(/\/course-space$/);
    await expect(page.getByRole('heading', { name: '我的课程', exact: true })).toBeVisible();
    await page.getByRole('button', { name: '打开课程：回归课程 B', exact: true }).click();
    await expect(page).toHaveURL(/workspace=course-b$/);
    await expect(page.getByRole('button', { name: '返回课程中心', exact: true })).toBeVisible();
    await page.goBack();
    await expect(page.getByRole('heading', { name: '我的课程', exact: true })).toBeVisible();
  });
}

test('course deletion is visible, cancellable, and removes only the confirmed card', async ({
  page,
}) => {
  await page.goto('/course-space');
  await page.getByRole('button', { name: '删除课程：回归课程 A', exact: true }).click();
  await expect(page.getByRole('alertdialog')).toContainText('回归课程 A');
  await page.getByRole('button', { name: '取消', exact: true }).click();
  await expect(
    page.getByRole('button', { name: '打开课程：回归课程 A', exact: true }),
  ).toBeVisible();
  await page.getByRole('button', { name: '删除课程：回归课程 A', exact: true }).click();
  await page.getByRole('button', { name: '确认删除课程', exact: true }).click();
  await expect(page.getByRole('alertdialog')).toHaveCount(0);
  await expect(page.getByRole('button', { name: '打开课程：回归课程 A', exact: true })).toHaveCount(
    0,
  );
  await expect(
    page.getByRole('button', { name: '打开课程：回归课程 B', exact: true }),
  ).toBeVisible();
});
