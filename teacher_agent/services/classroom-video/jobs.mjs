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

/** Fail the page request if the teacher service is briefly unavailable. */
export async function forwardTeacherCaptureRequest(route, options) {
  try {
    const response = await route.fetch(options);
    await route.fulfill({ response });
  } catch {
    // A context can also close while a request is in flight.
    await route.abort().catch(() => {});
  }
}

export const MAX_CONCURRENT_PAGES = 2;

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
  const activePages = new Map();
  job.activePages = activePages;
  let writes = Promise.resolve();
  function status(state, extra) {
    const [currentSceneId, phase] = activePages.entries().next().value ?? [];
    const snapshot = {
      completed: completed.size,
      failedPages: Object.fromEntries(failed),
      ...(currentSceneId && {
        currentSceneId,
        phase,
        activePages: Object.fromEntries(activePages),
      }),
      ...extra,
    };
    // The two lanes can change phase concurrently. Keep disk snapshots in that order.
    writes = writes.then(() => report(state, snapshot));
    return writes;
  }

  async function record(id, lane) {
    job.retries.delete(id);
    pending.delete(id);
    const clip = byId.get(id);
    if (!clip || completed.has(id) || activePages.has(id)) return;
    failed.delete(id);
    const phase = (value) => {
      activePages.set(id, value);
      return status('rendering');
    };
    try {
      await phase('loading');
      await capture(clip, phase, lane);
      completed.add(id);
    } catch (error) {
      failed.set(id, String(error?.message || error).slice(0, 800));
    } finally {
      activePages.delete(id);
    }
    await status('rendering');
  }

  async function runLane(lane) {
    while (job.retries.size || pending.size) {
      const id = job.retries.values().next().value ?? pending.values().next().value;
      await record(id, lane);
    }
  }

  // Publish the first clip before the other lanes contend for CPU and memory.
  const first = clips[0];
  if (!job.sceneId && first) await record(first.sceneId, 0);

  do {
    const lanes = await Promise.allSettled(
      Array.from({ length: MAX_CONCURRENT_PAGES }, (_, lane) => runLane(lane)),
    );
    const rejected = lanes.find((lane) => lane.status === 'rejected');
    if (rejected) throw rejected.reason;
    if (completed.size === clips.length) await status('ready');
    else {
      await status('failed', {
        error: failed.size ? '部分页面转换失败，可以逐页重试' : '还有页面待转换',
      });
    }
  } while (job.retries.size);
}
