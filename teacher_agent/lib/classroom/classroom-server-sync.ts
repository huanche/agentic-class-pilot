import type { Scene, Stage } from '@/lib/types/stage';

export interface ClassroomServerSnapshot {
  stage: Stage;
  scenes: Scene[];
}

export function canSyncClassroomSnapshot(
  classroomId: string,
  snapshot: { stage: Stage | null; scenes: Scene[]; generationComplete: boolean },
): snapshot is ClassroomServerSnapshot & { generationComplete: true } {
  return (
    snapshot.generationComplete &&
    snapshot.stage?.id === classroomId &&
    snapshot.scenes.length > 0
  );
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
