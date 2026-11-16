import { test, expect } from '@playwright/test';

test('group submits only selected children and restores remaining questions', async ({ page }, testInfo) => {
  const courses = [{ id: 'c', title: '课程', lessons: [{ id: 'lesson', title: '组合题课时', week: 1 }] }];
  let view = { sessionId: 's', userId: 'u', lessonId: 'lesson', courses, phase: 'discussion', typedTeaching: true,
    agentStage: 'recall', stateVersion: 1, contentGeneration: 0, currentTaskPublic: { taskId: 't' },
    messages: [], postclassMessages: [], questionGroups: [{ id: 'g', point_id: 'p', active: true,
      questions: [{ id: 'q1', prompt: '第一个事实', options: ['事实一', '错误一'] },
        { id: 'q2', prompt: '第二个事实', options: ['事实二', '错误二'] }], results: {} }] };
  await page.addInitScript(() => localStorage.setItem('student_last_course:u', 'c'));
  await page.route('**/api/session/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/identity')) return route.fulfill({ json: { userId: 'u', csrfToken: 'test' } });
    if (path.endsWith('/platform-entry')) return route.fulfill({ json: { platformUrl: '' } });
    if (path.endsWith('/start')) return route.fulfill({ json: { sessionId: 'catalog', userId: 'u', phase: 'idle', courses, messages: [], stateVersion: 0 } });
    if (path.endsWith('/commands')) {
      const command = route.request().postDataJSON();
      expect(command.payload.cardId).toBe('g');
      expect(command.payload.taskId).toBe('t');
      expect(command.payload.answers).toEqual({ q1: 0 });
      view = structuredClone(view);
      view.stateVersion++;
      view.questionGroups[0].results.q1 = { choice: 0, correct: true, answer: 0, explanation: '第一个事实的解释' };
      return route.fulfill({ json: { commandId: command.commandId, status: 'completed', sessionView: view } });
    }
    return route.fulfill({ json: view });
  });
  await page.goto('/app/');
  await page.getByRole('button', { name: /组合题课时/ }).click();
  await page.getByLabel('事实一', { exact: true }).check();
  await page.getByRole('button', { name: '提交已完成的题目' }).click();
  await expect(page.getByText('第一个事实的解释')).toBeVisible();
  await expect(page.getByLabel('事实一', { exact: true })).toBeDisabled();
  await expect(page.getByLabel('事实二', { exact: true })).toBeEnabled();
  await page.screenshot({ path: testInfo.outputPath('question-group.png'), fullPage: true });
  await page.reload();
  const lesson = page.getByRole('button', { name: /组合题课时/ });
  await expect(lesson).toBeVisible();
  await lesson.click();
  await expect(page.getByText('第一个事实的解释')).toBeVisible();
  await expect(page.getByLabel('事实二', { exact: true })).toBeEnabled();
});
