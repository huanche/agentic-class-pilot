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
  try {
    await Promise.race([
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
  }
  const alerts = (await page.locator('[role="alert"]:visible').allTextContents())
    .map((s) => s.trim())
    .filter(Boolean);
  if (alerts.length) throw new Error(`页面加载错误: ${alerts.join(' ').slice(0, 200)}`);
  // No screencast or narration may start before the readiness promise AND
  // visible-error check above have completed successfully.
  await onPhase('recording');
}
