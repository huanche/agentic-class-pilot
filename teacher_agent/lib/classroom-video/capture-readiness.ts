export const CAPTURE_SOURCE_LOAD_TIMEOUT_MS = 180_000;

/** A recording can only use the exact scene whose complete preparation resolved. */
export function createCaptureReadinessGate() {
  let generation = 0;
  let readyScene: string | null = null;
  return {
    async prepare(sceneId: string, prepare: () => Promise<void>) {
      const token = ++generation;
      readyScene = null;
      await prepare();
      if (token !== generation) throw new Error('页面已切换，请重新准备课件');
      readyScene = sceneId;
    },
    assertReady(sceneId: string) {
      if (readyScene !== sceneId) throw new Error('课件仍在加载，请等待原稿准备完成后再开始录制');
    },
    invalidate() {
      generation++;
      readyScene = null;
    },
  };
}
