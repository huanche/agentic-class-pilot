/** Capture's longer native-loading budget plus time for fonts and decoded images. */
export const CAPTURE_READY_TIMEOUT_MS = 210_000;

export async function prepareRecording(
  page,
  sceneId,
  onPhase = async () => {},
  timeout = CAPTURE_READY_TIMEOUT_MS,
) {
  await onPhase('loading');
  let timer;
  let failScript;
  const scriptFailure = new Promise((_, reject) => { failScript = reject; });
  const onScriptError = (cause) => {
    if (!String(cause.stack || '').includes('/onlyoffice-engine/')) return;
    const error = new Error(`原稿播放器初始化失败: ${cause.message}`);
    error.code = 'CAPTURE_SOURCE_SCRIPT_ERROR';
    failScript(error);
  };
  page.on('pageerror', onScriptError);
  try {
    await Promise.race([
      scriptFailure,
      page.evaluate(async (id) => {
        if (window.classroomCaptureError) throw new Error(window.classroomCaptureError);
        if (!window.classroomCapture) throw new Error('课件加载入口尚未就绪');
        await window.classroomCapture.ready(id);
      }, sceneId),
      new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error('原稿或页面资源加载超时，请重新加载')), timeout);
      }),
    ]);
  } finally {
    clearTimeout(timer);
    page.off('pageerror', onScriptError);
  }
  const alerts = (await page.locator('[role="alert"]:visible').allTextContents())
    .map((s) => s.trim())
    .filter(Boolean);
  if (alerts.length) throw new Error(`页面加载错误: ${alerts.join(' ').slice(0, 200)}`);
  // No screencast or narration may start before the readiness promise AND
  // visible-error check above have completed successfully.
  await onPhase('recording');
}

/** Retry an engine startup crash once, strictly before recording has begun. */
export async function prepareRecordingWithRetry(page, sceneId, onPhase, timeout) {
  try {
    await prepareRecording(page, sceneId, onPhase, timeout);
  } catch (error) {
    if (error.code !== 'CAPTURE_SOURCE_SCRIPT_ERROR') throw error;
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.waitForFunction(() => window.classroomCapture || window.classroomCaptureError);
    await prepareRecording(page, sceneId, onPhase, timeout);
  }
}
