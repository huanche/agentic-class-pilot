import assert from 'node:assert/strict';
import { chromium } from 'playwright-core';
import { prepareRecordingWithRetry } from './readiness.mjs';

const [room, version, scene] = process.argv.slice(2);
const origin = new URL(process.env.VIDEO_PUBLIC_ORIGIN).origin;
const teacher = 'http://agentic-teacher-prod:3200';
const grant = process.env.VIDEO_CAPTURE_GRANT;
const args = ['--no-sandbox', '--disable-dev-shm-usage'];
if (process.env.VIDEO_ORIGIN_IP)
  args.push(`--host-resolver-rules=MAP ${new URL(origin).hostname} ${process.env.VIDEO_ORIGIN_IP}`);
const browser = await chromium.launch({ executablePath: '/usr/bin/chromium', headless: true, args });

try {
  const context = await browser.newContext({
    viewport: { width: 1280, height: 720 }, serviceWorkers: 'block',
  });
  const page = await context.newPage();
  page.setDefaultTimeout(45_000);
  await context.route('**/*', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (['blob:', 'data:'].includes(url.protocol)) return route.continue();
    if (url.origin !== origin || !['GET', 'HEAD'].includes(request.method())) return route.abort();
    const headers = { ...request.headers() };
    if (url.pathname === '/onlyoffice/api/config') {
      if (url.searchParams.get('classroom') !== room || url.searchParams.get('scene') !== scene)
        return route.abort();
      const response = await fetch(
        `${teacher}/api/classroom?id=${room}&videoCapture=${version}&nativeScene=${scene}`,
        { headers: { 'x-classroom-render-grant': grant }, signal: AbortSignal.timeout(15_000) },
      );
      if (!response.ok) return route.fulfill({ status: 503 });
      const { nativeConfig } = await response.json();
      if (!nativeConfig?.steps?.length) return route.fulfill({ status: 422 });
      return route.fulfill({ json: nativeConfig });
    }
    if (url.pathname.startsWith('/onlyoffice')) return route.continue();
    if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/classroom-player/'))
      headers['x-classroom-render-grant'] = grant;
    const response = await route.fetch({ url: teacher + url.pathname + url.search, headers });
    return route.fulfill({ response });
  });

  await page.goto(`${origin}/classroom-player/${room}?capture=${version}`, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => window.classroomCapture || window.classroomCaptureError);
  await prepareRecordingWithRetry(page, scene);
  const native = page.locator('[data-native-pptx] iframe').first();
  await native.waitFor({ state: 'visible' });
  const dimensions = await native.boundingBox();
  assert.ok(dimensions?.width >= 400 && dimensions.height >= 300);
  const before = await native.screenshot();
  await native.evaluate((frame, sceneId) => new Promise((resolve, reject) => {
    const channel = 'agentic-native-pptx-v1';
    const id = Number.MAX_SAFE_INTEGER;
    function receive(event) {
      if (event.source !== frame.contentWindow || event.origin !== location.origin ||
          event.data?.channel !== channel || event.data.id !== id) return;
      removeEventListener('message', receive);
      clearTimeout(timer);
      if (event.data.event === 'ack') resolve();
      else reject(new Error(event.data.detail || 'Native animation failed'));
    }
    const timer = setTimeout(() => {
      removeEventListener('message', receive);
      reject(new Error('Native animation timed out'));
    }, 25_000);
    addEventListener('message', receive);
    frame.contentWindow.postMessage({ channel, id, sceneId, command: 'seek', step: 1 }, location.origin);
  }), scene);
  const after = await native.screenshot();
  assert.ok(!before.equals(after), 'The first native animation did not change the rendered slide');
  console.log('NATIVE_SMOKE_OK: original slide rendered and the first animation changed the frame');
} finally {
  await browser.close();
}
