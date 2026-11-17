/** Keep the expensive Chromium process warm. Each page owns and closes its own context. */
export function createBrowserSession(launch) {
  let browser;
  return {
    async newContext(options) {
      if (!browser?.isConnected()) browser = await launch();
      return browser.newContext(options);
    },
    async close() {
      const current = browser;
      browser = undefined;
      await current?.close();
    },
  };
}

/** Record independent pages and persist progress even when a page cannot be captured. */
export async function renderVideoJob(job, clips, previous, { isReady, capture, report }) {
  const byId = new Map(clips.map((clip) => [clip.sceneId, clip]));
  const completed = new Set();
  for (const clip of clips) {
    if (await isReady(clip)) completed.add(clip.sceneId);
  }
  const failed = new Map(
    Object.entries(previous?.failedPages ?? {}).filter(
      ([id, error]) => byId.has(id) && !completed.has(id) && typeof error === 'string',
    ),
  );
  const pending = new Set(job.sceneId ? [job.sceneId] : byId.keys());
  const status = (state, extra) =>
    report(state, { completed: completed.size, failedPages: Object.fromEntries(failed), ...extra });

  while (true) {
    const id = job.retries.values().next().value ?? pending.values().next().value;
    if (id === undefined) {
      if (completed.size === clips.length) await status('ready');
      else
        await status('failed', {
          error: failed.size ? '部分页面转换失败，可以逐页重试' : '还有页面待转换',
        });
      if (!job.retries.size) return;
      continue;
    }
    job.retries.delete(id);
    pending.delete(id);
    if (completed.has(id)) continue;
    const clip = byId.get(id);
    if (!clip) continue;
    job.currentSceneId = id;
    failed.delete(id);
    const phase = (value) => status('rendering', { currentSceneId: id, phase: value });
    await phase('loading');
    try {
      await capture(clip, phase);
      completed.add(id);
    } catch (error) {
      failed.set(id, String(error?.message || error).slice(0, 800));
    } finally {
      job.currentSceneId = undefined;
    }
    await status('rendering');
  }
}
