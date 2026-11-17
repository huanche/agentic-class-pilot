import { test, expect } from '@playwright/test';

test('formal student card stays in the teacher timeline and accepts follow-up questions', async ({ page }) => {
  const courses = [{ id: 'c', title: '课程', lessons: [{ id: 'lesson', title: '题卡课时', week: 1, playerUrl: '/demo-player' }] }];
  let view = { sessionId: 's', userId: 'u', lessonId: 'lesson', courses, phase: 'discussion', typedTeaching: true,
    agentStage: 'recall', stateVersion: 1, contentGeneration: 0, currentTaskPublic: { taskId: 't' },
    messages: [{ role: 'assistant', text: '请完成这张题卡。', cardId: 'g' }], postclassMessages: [],
    questionGroups: [{ id: 'g', point_id: 'p', active: true,
      phase: 'discussion', questions: [{ id: 'q1', prompt: '光合作用的场所？', options: ['叶绿体', '细胞核'] }], results: {} }] };
  await page.addInitScript(() => localStorage.setItem('student_last_course:u', 'c'));
  await page.route('**/api/session/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/identity')) return route.fulfill({ json: { userId: 'u', csrfToken: 'test' } });
    if (path.endsWith('/platform-entry')) return route.fulfill({ json: { platformUrl: '' } });
    if (path.endsWith('/start')) return route.fulfill({ json: { sessionId: 'catalog', userId: 'u', phase: 'idle', courses, messages: [], stateVersion: 0 } });
    if (path.endsWith('/begin/lesson')) return route.fulfill({ json: view });
    if (path.endsWith('/commands')) {
      const command = route.request().postDataJSON();
      expect(command.payload.taskId).toBe('t');
      view = structuredClone(view);
      view.stateVersion++;
      if (command.payload.cardId) {
        expect(command.payload.answers).toEqual({ q1: 0 });
        view.questionGroups[0].results.q1 = { choice: 0, correct: true, answer: 0, explanation: '叶绿体吸收光能' };
        view.agentStage = 'wrapup';
        view.reviewingCard = true;
      } else {
        expect(command.payload.text).toBe('为什么是叶绿体？');
        view.messages.push({ role: 'student', text: '为什么是叶绿体？' },
          { role: 'assistant', text: '因为叶绿体含有叶绿素。' });
      }
      return route.fulfill({ json: { commandId: command.commandId, status: 'completed', sessionView: view } });
    }
    return route.fulfill({ json: view });
  });
  await page.goto('/app/');
  await page.getByRole('button', { name: /题卡课时/ }).click();
  await page.addStyleTag({ content: '.conversation-log { height: 300px !important; padding-bottom: 600px !important; }' });
  await page.getByLabel('叶绿体', { exact: true }).check();
  const submit = page.getByRole('button', { name: '提交已完成的题目' });
  await submit.scrollIntoViewIfNeeded();
  const log = page.getByRole('log');
  const scrollBefore = await log.evaluate(element => element.scrollTop);
  await submit.click();
  await expect(page.getByText('叶绿体吸收光能')).toBeVisible();
  await expect(page.getByText('回答正确 √')).toBeVisible();
  await expect(page.getByText('你的答案：叶绿体')).toBeVisible();
  await expect(page.locator('.msg--me')).toHaveCount(0);
  expect(await log.evaluate(element => element.scrollTop)).toBeLessThanOrEqual(scrollBefore + 5);
  await page.getByRole('textbox', { name: '输入复述或讨论' }).fill('为什么是叶绿体？');
  await page.getByRole('button', { name: '发送' }).click();
  await expect(page.getByText('因为叶绿体含有叶绿素。')).toBeVisible();
  expect(await page.evaluate(() => Boolean(document.querySelector('.question-group')
    .compareDocumentPosition(document.querySelector('.msg--me')) & Node.DOCUMENT_POSITION_FOLLOWING))).toBe(true);
});

test('group submits only selected children and restores remaining questions', async ({ page }, testInfo) => {
  const courses = [{ id: 'c', title: '课程', lessons: [{ id: 'lesson', title: '组合题课时', week: 1 }] }];
  let view = { sessionId: 's', userId: 'u', lessonId: 'lesson', courses, phase: 'discussion', typedTeaching: true,
    agentStage: 'recall', stateVersion: 1, contentGeneration: 0, currentTaskPublic: { taskId: 't' }, canGoNextPoint: true,
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
      if (command.type === 'next_point') {
        expect(command.payload).toEqual({ taskId: 't' });
        view = structuredClone(view);
        view.stateVersion++;
        view.currentTaskPublic = { taskId: 'next' };
        view.learningProgress = { currentPoint: '下一个知识点' };
        view.messages = [{ role: 'assistant', text: '开始学习下一个知识点。', phase: 'recall' }];
        view.questionGroups[0].active = false;
        view.canGoNextPoint = false;
        return route.fulfill({ json: { commandId: command.commandId, status: 'completed', sessionView: view } });
      }
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
  await expect(page.getByRole('log').getByLabel('事实一', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '提交已完成的题目' }).first().click();
  await expect(page.getByText('第一个事实的解释')).toBeVisible();
  await expect(page.getByLabel('事实一', { exact: true })).toBeDisabled();
  await expect(page.getByLabel('事实二', { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '下一题 →' }).click();
  await expect(page.getByLabel('事实二', { exact: true })).toBeEnabled();
  await page.getByRole('button', { name: '← 上一题' }).click();
  await expect(page.getByText('第一个事实的解释')).toBeVisible();
  await expect(page.getByLabel('事实一', { exact: true })).toBeChecked();
  await page.getByRole('button', { name: '下一题 →' }).click();
  await expect(page.getByLabel('事实二', { exact: true })).toBeEnabled();
  const directory = page.getByRole('navigation', { name: '知识点对话位置' });
  await directory.getByRole('button', { name: '下一个知识点' }).click();
  await expect(page.getByRole('log')).toContainText('开始学习下一个知识点。');
  await expect(page.getByText(/当前知识点：/)).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath('question-group.png'), fullPage: true });
  await page.reload();
  const lesson = page.getByRole('button', { name: /组合题课时/ });
  await expect(lesson).toBeVisible();
  await lesson.click();
  await expect(page.getByRole('button', { name: '下一个知识点' })).toBeDisabled();
});

test('wrong answer and its original explanation stay on the teacher card after reload', async ({ page }) => {
  const courses = [{ id: 'c', title: '课程', lessons: [{ id: 'lesson', title: '错题测试', week: 1, playerUrl: '/demo-player' }] }];
  let view = { sessionId: 's', userId: 'u', lessonId: 'lesson', courses, phase: 'discussion', typedTeaching: true,
    agentStage: 'recall', stateVersion: 1, contentGeneration: 0, currentTaskPublic: { taskId: 't' },
    messages: [{ role: 'assistant', text: '请看题卡。', cardId: 'g' }],
    questionGroups: [{ id: 'g', point_id: 'p', phase: 'discussion', active: true,
      questions: [{ id: 'q1', prompt: '光合作用的场所？', options: ['叶绿体', '细胞核'] }], results: {} }] };
  await page.addInitScript(() => localStorage.setItem('student_last_course:u', 'c'));
  await page.route('**/api/session/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/identity')) return route.fulfill({ json: { userId: 'u', csrfToken: 'test' } });
    if (path.endsWith('/platform-entry')) return route.fulfill({ json: { platformUrl: '' } });
    if (path.endsWith('/start')) return route.fulfill({ json: { sessionId: 'catalog', userId: 'u', phase: 'idle', courses, messages: [], stateVersion: 0 } });
    if (path.endsWith('/begin/lesson')) return route.fulfill({ json: view });
    if (path.endsWith('/commands')) {
      const command = route.request().postDataJSON();
      view = structuredClone(view);
      view.stateVersion++;
      if (command.type === 'finish') view.phase = 'done';
      else {
        expect(command.payload.cardId).toBe('g');
        expect(command.payload.answers).toEqual({ q1: 1 });
        view.questionGroups[0].results.q1 = { choice: 1, correct: false, answer: 0,
          explanation: '叶绿体含有叶绿素，能吸收光能。' };
        view.messages.push({ role: 'student', text: '光合作用的场所？：选择 细胞核' },
          { role: 'assistant', text: '本组题已完成。可以查看解析、继续提问，准备好后再切换知识点。' });
      }
      return route.fulfill({ json: { commandId: command.commandId, status: 'completed', sessionView: view } });
    }
    return route.fulfill({ json: view });
  });
  await page.goto('/app/');
  await page.getByRole('button', { name: /错题测试/ }).click();
  await page.getByLabel('细胞核', { exact: true }).check();
  await page.getByRole('button', { name: '提交已完成的题目' }).click();
  await expect(page.getByText('回答错误 ×')).toBeVisible();
  await expect(page.getByText('你的答案：细胞核')).toBeVisible();
  await expect(page.getByText('正确答案：叶绿体')).toBeVisible();
  await expect(page.getByText('解析：叶绿体含有叶绿素，能吸收光能。')).toBeVisible();
  await expect(page.locator('.msg--me')).toHaveCount(0);
  await page.reload();
  await page.getByRole('button', { name: /错题测试/ }).click();
  await expect(page.getByText('回答错误 ×')).toBeVisible();
  await expect(page.getByLabel('细胞核', { exact: true })).toBeChecked();
  await expect(page.getByText('解析：叶绿体含有叶绿素，能吸收光能。')).toBeVisible();
  await page.getByRole('button', { name: '结束本课并查看反馈' }).click();
  await page.getByText('查看历史会话与题卡（2 项）').click();
  await expect(page.getByText('回答错误 ×')).toBeVisible();
  await expect(page.getByText('解析：叶绿体含有叶绿素，能吸收光能。')).toBeVisible();
});

test('postclass resumes an unfinished classroom card after reload and submits through card command', async ({ page }) => {
  const courses = [{ id: 'c', title: 'course', lessons: [{ id: 'lesson', title: 'continued card', week: 1 }] }];
  let view = { sessionId: 's', userId: 'u', lessonId: 'lesson', courses, phase: 'done', typedTeaching: true,
    postclassStage: 'remediation', agentStage: 'recall', stateVersion: 1, contentGeneration: 0,
    currentTaskPublic: { taskId: 't' }, messages: [],
    postclassMessages: [{ role: 'assistant', text: 'Continue original card', cardId: 'g' }],
    questionGroups: [{ id: 'g', point_id: 'p', phase: 'discussion', active: true,
      questions: [{ id: 'q1', prompt: 'first fact', options: ['yes', 'no'] },
        { id: 'q2', prompt: 'second fact', options: ['right', 'wrong'] }],
      results: { q1: { choice: 0, correct: true, answer: 0, explanation: 'first explanation' } } }] };
  await page.route('**/api/session/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/identity')) return route.fulfill({ json: { userId: 'u', csrfToken: 'test' } });
    if (path.endsWith('/platform-entry')) return route.fulfill({ json: { platformUrl: '' } });
    if (path.endsWith('/start')) return route.fulfill({ json: { sessionId: 'catalog', userId: 'u', phase: 'idle', courses, messages: [], stateVersion: 0 } });
    if (path.endsWith('/commands')) {
      const command = route.request().postDataJSON();
      if (command.type === 'continue_after_class') {
        return route.fulfill({ json: { commandId: command.commandId, status: 'completed', sessionView: view } });
      }
      expect(command.type).toBe('postclass_answer');
      expect(command.payload.cardId).toBe('g');
      expect(command.payload.answers).toEqual({ q2: 0 });
      view = structuredClone(view);
      view.stateVersion++;
      view.questionGroups[0].results.q2 = { choice: 0, correct: true, answer: 0, explanation: 'second explanation' };
      return route.fulfill({ json: { commandId: command.commandId, status: 'completed', sessionView: view } });
    }
    return route.fulfill({ json: view });
  });
  await page.goto('/app/?course_id=c');
  await page.getByRole('button', { name: /continued card/ }).click();
  await page.getByRole('button', { name: '继续巩固', exact: true }).click();
  await expect(page.getByText('first explanation')).toBeVisible();
  await page.reload();
  await page.getByRole('button', { name: /continued card/ }).click();
  await page.getByRole('button', { name: '继续巩固', exact: true }).click();
  await expect(page.getByText('first explanation')).toBeVisible();
  await page.getByRole('button', { name: '下一题 →' }).click();
  await page.getByLabel('right', { exact: true }).check();
  await page.getByRole('button', { name: '提交已完成的题目' }).click();
  await expect(page.getByText('second explanation')).toBeVisible();
});
