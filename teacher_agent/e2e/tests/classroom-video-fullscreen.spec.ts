import { expect, test, type Page } from '@playwright/test';

async function createVideoFixture(page: Page) {
  return page.evaluate(async () => {
    const canvas = document.createElement('canvas');
    canvas.width = 320;
    canvas.height = 240;
    const context = canvas.getContext('2d')!;
    context.fillStyle = '#fcf7e9';
    context.fillRect(0, 0, canvas.width, canvas.height);
    const stream = canvas.captureStream(30);
    const recorder = new MediaRecorder(stream, { mimeType: 'video/webm;codecs=vp8' });
    const output = new Promise<number[]>((resolve, reject) => {
      recorder.ondataavailable = (event) => {
        event.data
          .arrayBuffer()
          .then((buffer) => resolve(Array.from(new Uint8Array(buffer))), reject);
      };
      recorder.onerror = reject;
    });
    recorder.start();
    for (let i = 0; i < 8; i++) {
      context.fillRect(i, i, 16, 16);
      await new Promise((resolve) => setTimeout(resolve, 40));
    }
    recorder.stop();
    stream.getTracks().forEach((track) => track.stop());
    return output;
  });
}

test('standalone videos fit the window and fullscreen gives all available height to the picture', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 650 });
  const bytes = await createVideoFixture(page);
  expect(bytes.length).toBeGreaterThan(0);

  const scenes = [
    { id: 'first', title: '数组与排序', type: 'slide', actions: [] },
    { id: 'second', title: '冒泡排序', type: 'slide', actions: [] },
  ];
  await page.route('**/api/classroom?**', (route) =>
    route.fulfill({
      json: {
        manifest: {
          version: 'test-version',
          title: 'C 语言实验',
          stage: { id: 'fullscreen-test', name: 'C 语言实验' },
          status: { state: 'ready', completed: 2, total: 2 },
          scenes,
          clips: scenes.map((scene) => ({
            sceneId: scene.id,
            url: '/fullscreen-fixture.webm',
            captions: [],
          })),
        },
      },
    }),
  );
  await page.route('**/fullscreen-fixture.webm', (route) =>
    route.fulfill({ contentType: 'video/webm', body: Buffer.from(bytes) }),
  );
  await page.goto('/classroom-player/fullscreen-test');

  const video = page.locator('video');
  const frame = page.locator('[data-course-player-frame]');
  const surface = page.locator('[data-course-video-surface]');
  await expect(page.getByRole('heading', { name: '数组与排序' })).toBeVisible();
  await expect.poll(() => video.evaluate((element) => element.videoWidth)).toBe(320);
  await expect
    .poll(async () => {
      const picture = await surface.boundingBox();
      return picture && Math.abs(picture.width / picture.height - 4 / 3) < 0.01;
    })
    .toBe(true);
  expect((await surface.boundingBox())!.height).toBeGreaterThan(500);
  expect((await frame.boundingBox())!.y + (await frame.boundingBox())!.height).toBeLessThan(650);

  await page.getByRole('button', { name: '全屏', exact: true }).click();
  await expect
    .poll(() => frame.evaluate((element) => document.fullscreenElement === element))
    .toBe(true);
  await expect
    .poll(() =>
      surface.evaluate((element) => Math.abs(element.getBoundingClientRect().height - innerHeight)),
    )
    .toBeLessThan(2);
  await expect(page.locator('[data-course-navigation]')).toHaveCount(0);
  await expect(page.getByRole('button', { name: '下一节' })).toBeVisible();
  await expect(page.getByRole('button', { name: '字幕' })).toBeVisible();

  await page.getByRole('button', { name: '退出全屏' }).click();
  await expect.poll(() => page.evaluate(() => document.fullscreenElement === null)).toBe(true);
  await expect(page.getByRole('button', { name: '下一页' })).toBeVisible();
});

test('a teacher can play an existing video, see both active conversions, and retry a failed page', async ({
  page,
}) => {
  let retry: unknown;
  const version = 'preview-test';
  const bytes = await createVideoFixture(page);
  const scenes = ['可播放的第一页', '原稿打不开的第二页', '加载中的第三页', '合成中的第四页'].map(
    (title, index) => ({
      id: 's' + (index + 1),
      title,
      type: 'slide',
    }),
  );
  await page.route('**/api/classroom?**', (route) => {
    const request = route.request();
    if (request.method() === 'POST') {
      const body = request.postDataJSON();
      if (body.operation === 'retry-video') retry = body;
      return route.fulfill({ json: { version } });
    }
    return route.fulfill({
      json: {
        manifest: {
          version,
          title: '草稿预览',
          stage: { id: version, name: '草稿预览' },
          scenes,
          status: {
            state: 'rendering',
            completed: 1,
            total: 4,
            readySceneIds: ['s1'],
            failedPages: retry ? {} : { s2: '原稿播放器初始化失败' },
            currentSceneId: retry ? 's2' : 's3',
            phase: 'loading',
            activePages: { [retry ? 's2' : 's3']: 'loading', s4: 'encoding' },
          },
          clips: [{ sceneId: 's1', url: '/first-test-fixture.webm' }],
        },
      },
    });
  });
  await page.route('**/first-test-fixture.webm', (route) =>
    route.fulfill({
      contentType: 'video/webm',
      body: Buffer.from(bytes),
    }),
  );
  await page.goto('/classroom-player/preview-test?video=1&draft=1');
  const video = page.locator('video');
  await expect.poll(() => video.evaluate((element) => element.videoWidth)).toBe(320);
  await page.getByRole('button', { name: '播放视频' }).click();
  await expect.poll(() => video.evaluate((element) => element.currentTime)).toBeGreaterThan(0);
  await expect(page.getByText('已完成 1/4 页 · 失败 1 页')).toBeVisible();
  await page.getByRole('button', { name: '课程目录' }).click();
  await expect(page.getByRole('button', { name: /加载中的第三页.*转换中/ })).toBeVisible();
  await page.getByRole('button', { name: /合成中的第四页.*转换中/ }).click();
  await expect(page.getByText('正在合成本页 MP4')).toBeVisible();
  await page.getByRole('button', { name: '课程目录' }).click();
  await page.getByRole('button', { name: /原稿打不开的第二页.*转换失败/ }).click();
  await expect(page.locator('video')).toHaveCount(0);
  await expect(page.getByText('本页视频转换失败')).toBeVisible();
  await page.getByRole('button', { name: '重试本页' }).click();
  await expect.poll(() => retry).toEqual({ operation: 'retry-video', sceneId: 's2' });
  await expect(page.getByText('正在加载本页原稿')).toBeVisible();
  await page.getByRole('button', { name: '上一页' }).click();
  await expect(video).toHaveAttribute('src', '/first-test-fixture.webm');
});

test('puts trial narration below the video and revoices the selected page', async ({ page }) => {
  const version = 'trial-preview';
  const stage = {
    id: version,
    name: '测试课件',
    coursewareTrial: { courseId: 'test-course', revision: 3 },
  };
  const scenes = [
    {
      id: 's1',
      title: '一维数组',
      type: 'slide',
      order: 1,
      actions: [{ id: 'speech-1', type: 'speech', text: '数组有 20 个元素。' }],
    },
  ];
  let revoice: unknown;
  await page.route('**/api/classroom?**', (route) => {
    const request = route.request();
    if (request.method() === 'POST') return route.fulfill({ json: { version } });
    if (!new URL(request.url()).searchParams.has('video')) {
      return route.fulfill({ json: { classroom: { stage, scenes } } });
    }
    return route.fulfill({
      json: {
        manifest: {
          version,
          title: stage.name,
          stage,
          scenes,
          status: { state: 'ready', completed: 1, total: 1 },
          clips: [{ sceneId: 's1', url: '/trial-fixture.webm' }],
        },
      },
    });
  });
  await page.route('**/trial-fixture.webm', (route) =>
    route.fulfill({ contentType: 'video/webm', body: Buffer.alloc(0) }),
  );
  await page.route('**/classrooms/trial-preview/narration', (route) => {
    revoice = route.request().postDataJSON();
    return route.fulfill({ json: { success: true, revision: 4 } });
  });
  await page.goto('/classroom-player/trial-preview?video=1&draft=1&trial=1');
  const summary = page.getByText('逐页讲稿与原稿检查');
  await expect(summary).toBeVisible();
  expect(
    await page.locator('video').evaluate((video) => {
      const panel = document.querySelector('[data-trial-narration]');
      return Boolean(
        panel && video.compareDocumentPosition(panel) & Node.DOCUMENT_POSITION_FOLLOWING,
      );
    }),
  ).toBe(true);
  await summary.click();
  await page.getByRole('button', { name: '用优化读法重新配音' }).click();
  await expect
    .poll(() => revoice)
    .toEqual({
      operation: 'trial-revise',
      sceneId: 's1',
      revision: 3,
      segments: {},
      regenerate: false,
      revoice: true,
    });
});
