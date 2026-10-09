import type { Scene, Stage } from '@/lib/types/stage';

export interface ClassroomServerSnapshot {
  stage: Stage;
  scenes: Scene[];
}

export function canSyncClassroomSnapshot(
  classroomId: string,
  snapshot: { stage: Stage | null; scenes: Scene[]; generationComplete: boolean },
): snapshot is ClassroomServerSnapshot & { generationComplete: boolean } {
  return (
    snapshot.stage?.id === classroomId &&
    snapshot.scenes.length > 0
  );
}

// Only one write may be in flight for a classroom. Newer snapshots replace
// queued ones, so a slow response cannot overwrite pages generated later.
export function createClassroomSnapshotSyncQueue(
  send: (snapshot: ClassroomServerSnapshot) => Promise<void> = syncClassroomSnapshot,
  onError: (error: unknown) => void = () => {},
  delayMs = 500,
) {
  let pending: ClassroomServerSnapshot | null = null;
  let writing = false;
  let disposed = false;
  let timer: ReturnType<typeof setTimeout> | null = null;

  const schedule = (delay: number) => {
    if (disposed || writing || timer) return;
    timer = setTimeout(() => {
      timer = null;
      void flush();
    }, delay);
  };

  const flush = async () => {
    if (disposed || writing || !pending) return;
    const snapshot = pending;
    pending = null;
    writing = true;
    let failed = false;
    try {
      await send(snapshot);
    } catch (error) {
      onError(error);
      // Never replace a newer snapshot with the failed older one.
      pending ??= snapshot;
      failed = true;
    } finally {
      writing = false;
      if (pending) schedule(failed ? 2000 : delayMs);
    }
  };

  return {
    enqueue(snapshot: ClassroomServerSnapshot) {
      if (disposed) return;
      pending = snapshot;
      schedule(delayMs);
    },
    dispose() {
      disposed = true;
      pending = null;
      if (timer) clearTimeout(timer);
      timer = null;
    },
  };
}

export async function syncClassroomSnapshot(
  snapshot: ClassroomServerSnapshot,
  fetcher: typeof fetch = fetch,
): Promise<void> {
  const response = await fetcher('/api/classroom', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(snapshot),
  });
  if (response.ok) return;

  const result = (await response.json().catch(() => undefined)) as
    | { error?: string; message?: string }
    | undefined;
  throw new Error(result?.error || result?.message || `Classroom sync failed (${response.status})`);
}
