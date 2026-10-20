/** Refresh an already mounted teacher preview as its server worker adds pages.
 * Each read finishes before the next is scheduled, so a slow load cannot keep
 * invalidating itself with a newer load token. Never starts generation.
 */
export function watchBackgroundClassroomGeneration({
  readStatus,
  refresh,
  intervalMs = 2500,
}: {
  readStatus: () => Promise<string | undefined>;
  refresh: (isCurrent: () => boolean) => Promise<boolean>;
  intervalMs?: number;
}): () => void {
  let disposed = false;
  let timer: ReturnType<typeof setTimeout>;
  const isCurrent = () => !disposed;
  const schedule = () => {
    if (!disposed) timer = setTimeout(() => void poll(), intervalMs);
  };
  const poll = async () => {
    let status: string | undefined;
    try {
      status = await readStatus();
    } catch {
      // A job metadata failure must not prevent the classroom read itself.
    }
    if (disposed) return;
    try {
      const complete = await refresh(isCurrent);
      // Always read the final partial snapshot after cancellation/failure.
      if (complete || status === 'cancelled' || status === 'failed') return;
    } catch {
      // Keep the visible pages and retry transient read failures.
    }
    schedule();
  };
  schedule();
  return () => {
    disposed = true;
    clearTimeout(timer);
  };
}
