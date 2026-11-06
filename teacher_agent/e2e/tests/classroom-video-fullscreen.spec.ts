import { expect, test } from '@playwright/test';

test('standalone videos fit the window and fullscreen gives all available height to the picture', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 650 });
  const bytes = await page.evaluate(async () => {
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
        event.data.arrayBuffer().then((buffer) => resolve(Array.from(new Uint8Array(buffer))), reject);
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
            sceneId: scene.id, url: '/fullscreen-fixture.webm', captions: [],
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
  await expect.poll(async () => {
    const picture = await surface.boundingBox();
    return picture && Math.abs(picture.width / picture.height - 4 / 3) < 0.01;
  }).toBe(true);
  expect((await surface.boundingBox())!.height).toBeGreaterThan(500);
  expect((await frame.boundingBox())!.y + (await frame.boundingBox())!.height).toBeLessThan(650);

  await page.getByRole('button', { name: '全屏', exact: true }).click();
  await expect.poll(() => frame.evaluate((element) => document.fullscreenElement === element)).toBe(true);
  await expect.poll(() =>
    surface.evaluate((element) => Math.abs(element.getBoundingClientRect().height - innerHeight)),
  ).toBeLessThan(2);
  await expect(page.locator('[data-course-navigation]')).toHaveCount(0);
  await expect(page.getByRole('button', { name: '下一节' })).toBeVisible();
  await expect(page.getByRole('button', { name: '字幕' })).toBeVisible();

  await page.getByRole('button', { name: '退出全屏' }).click();
  await expect.poll(() => page.evaluate(() => document.fullscreenElement === null)).toBe(true);
  await expect(page.getByRole('button', { name: '下一页' })).toBeVisible();
});
