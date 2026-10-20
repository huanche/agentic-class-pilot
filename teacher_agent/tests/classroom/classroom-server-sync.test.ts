import { describe, expect, it, vi } from 'vitest';
import {
  canSyncClassroomSnapshot,
  createClassroomSnapshotSyncQueue,
  syncClassroomSnapshot,
  ClassroomSnapshotConflictError,
} from '@/lib/classroom/classroom-server-sync';
import type { Scene, Stage } from '@/lib/types/stage';

const stage = { id: 'classroom-1', name: 'Lesson' } as Stage;
const scenes = [{ id: 'scene-1', stageId: stage.id, type: 'slide' }] as Scene[];

describe('classroom server sync', () => {
  it('keeps an unfinished server task read-only until it has completed', () => {
    const serverStage = {
      ...stage,
      generationPlan: { version: 1 as const, outlines: [], complete: false, serverJobId: 'job-1' },
    };
    expect(
      canSyncClassroomSnapshot(stage.id, { stage: serverStage, scenes, generationComplete: false }),
    ).toBe(false);
    serverStage.generationPlan.complete = true;
    expect(
      canSyncClassroomSnapshot(stage.id, { stage: serverStage, scenes, generationComplete: true }),
    ).toBe(true);
  });
  it('syncs partial and complete non-empty snapshots for the current classroom', () => {
    expect(canSyncClassroomSnapshot(stage.id, { stage, scenes, generationComplete: true })).toBe(
      true,
    );
    expect(canSyncClassroomSnapshot(stage.id, { stage, scenes, generationComplete: false })).toBe(
      true,
    );
    expect(canSyncClassroomSnapshot('another', { stage, scenes, generationComplete: true })).toBe(
      false,
    );
    expect(
      canSyncClassroomSnapshot(stage.id, { stage, scenes: [], generationComplete: true }),
    ).toBe(false);
  });

  it('serializes writes and keeps the newest generated page list', async () => {
    vi.useFakeTimers();
    try {
      let releaseFirst!: () => void;
      const firstWrite = new Promise<void>((resolve) => {
        releaseFirst = resolve;
      });
      const send = vi.fn().mockReturnValueOnce(firstWrite).mockResolvedValue(undefined);
      const queue = createClassroomSnapshotSyncQueue(send, undefined, 10);
      const twoPages = { stage, scenes: [...scenes, { ...scenes[0], id: 'scene-2' }] };
      const threePages = { stage, scenes: [...twoPages.scenes, { ...scenes[0], id: 'scene-3' }] };

      queue.enqueue({ stage, scenes });
      await vi.advanceTimersByTimeAsync(10);
      queue.enqueue(twoPages);
      queue.enqueue(threePages);
      await vi.advanceTimersByTimeAsync(10);
      expect(send).toHaveBeenCalledTimes(1);
      releaseFirst();
      await vi.advanceTimersByTimeAsync(10);
      expect(send).toHaveBeenCalledTimes(2);
      expect(send).toHaveBeenLastCalledWith(threePages);
      queue.dispose();
    } finally {
      vi.useRealTimers();
    }
  });

  it('retries a failed save with the latest snapshot', async () => {
    vi.useFakeTimers();
    try {
      const send = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValue(undefined);
      const queue = createClassroomSnapshotSyncQueue(send, undefined, 10);
      queue.enqueue({ stage, scenes });
      await vi.advanceTimersByTimeAsync(10);
      expect(send).toHaveBeenCalledTimes(1);
      await vi.advanceTimersByTimeAsync(2000);
      expect(send).toHaveBeenCalledTimes(2);
      queue.dispose();
    } finally {
      vi.useRealTimers();
    }
  });

  it('posts the full stage and scene list to classroom storage', async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: true });

    await syncClassroomSnapshot({ stage, scenes }, fetcher as unknown as typeof fetch);

    expect(fetcher).toHaveBeenCalledWith('/api/classroom', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ stage, scenes }),
    });
  });

  it('drops every queued stale snapshot on conflict instead of retrying it', async () => {
    vi.useFakeTimers();
    try {
      let reject!: (error: Error) => void;
      const send = vi.fn(
        () =>
          new Promise<void>((_resolve, fail) => {
            reject = fail;
          }),
      );
      const onConflict = vi.fn();
      const queue = createClassroomSnapshotSyncQueue(send, onConflict, 10);
      queue.enqueue({ stage, scenes });
      await vi.advanceTimersByTimeAsync(10);
      queue.enqueue({ stage, scenes: [...scenes, { ...scenes[0], id: 'new' }] });
      reject(new ClassroomSnapshotConflictError('outdated'));
      await vi.advanceTimersByTimeAsync(5000);
      queue.enqueue({ stage, scenes });
      await vi.advanceTimersByTimeAsync(5000);
      expect(send).toHaveBeenCalledTimes(1);
      expect(onConflict).toHaveBeenCalledOnce();
      queue.resumeAfterReload();
      send.mockResolvedValueOnce(undefined);
      queue.enqueue({ stage, scenes });
      await vi.advanceTimersByTimeAsync(10);
      expect(send).toHaveBeenCalledTimes(2);
      queue.dispose();
    } finally {
      vi.useRealTimers();
    }
  });

  it('classifies a 409 response as a reload conflict', async () => {
    const fetcher = vi.fn().mockResolvedValue({
      ok: false,
      status: 409,
      json: async () => ({ error: '服务器课件已更新' }),
    });
    await expect(
      syncClassroomSnapshot({ stage, scenes }, fetcher as typeof fetch),
    ).rejects.toBeInstanceOf(ClassroomSnapshotConflictError);
  });

  it('surfaces a server error', async () => {
    const fetcher = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      json: vi.fn().mockResolvedValue({ error: 'storage unavailable' }),
    });

    await expect(
      syncClassroomSnapshot({ stage, scenes }, fetcher as unknown as typeof fetch),
    ).rejects.toThrow('storage unavailable');
  });
});
