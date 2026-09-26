/**
 * Process-scoped startup work.
 *
 * Next calls `register` once per server instance, before it serves a request.
 * That makes it the only place in this app where a background schedule can
 * live: a route module has no such guarantee — it can be instantiated more than
 * once and gets no shutdown hook — so anything periodic started from one is
 * really started per instantiation.
 *
 * `register` must return before the server is ready, so nothing here may block
 * on I/O. Starting a timer does not.
 */
export async function register(): Promise<void> {
  // Also invoked for the Edge runtime, which has neither `pg` nor timers we
  // want; the persistence stack is Node-only.
  if (process.env.NEXT_RUNTIME !== 'nodejs') return;

  // Imported dynamically so the Edge bundle never pulls in `pg`.
  const { startAssetCollectorSchedule } =
    await import('@/lib/persistence/asset-collector-schedule');
  startAssetCollectorSchedule();

  // A restart (redeploy, crash) kills in-flight artifact jobs mid-run; without
  // this sweep they stay "running" in the teacher UI until a same-scope job is
  // resubmitted. Fire-and-forget so readiness never blocks on the database.
  // The import can throw when the storage mode is misconfigured — that must
  // not take the whole server down with it.
  try {
    const { sweepAllStaleCourseJobs } = await import('@/lib/server/course-space-storage');
    void sweepAllStaleCourseJobs()
      .then((stale) => {
        if (stale.length > 0)
          console.info(`[startup] marked ${stale.length} stale artifact job(s) failed`);
      })
      .catch((error) => console.warn('[startup] stale artifact job sweep failed:', error));
  } catch (error) {
    console.warn('[startup] stale artifact job sweep unavailable:', error);
  }
}
