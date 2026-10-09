import { describe, expect, it, vi } from 'vitest';
import {
  canSyncClassroomSnapshot,
  syncClassroomSnapshot,
} from '@/lib/classroom/classroom-server-sync';
import type { Scene, Stage } from '@/lib/types/stage';

const stage = { id: 'classroom-1', name: 'Lesson' } as Stage;
const scenes = [{ id: 'scene-1', stageId: stage.id, type: 'slide' }] as Scene[];

describe('classroom server sync', () => {
  it('only syncs a complete non-empty snapshot for the current classroom', () => {
    expect(canSyncClassroomSnapshot(stage.id, { stage, scenes, generationComplete: true })).toBe(
      true,
    );
    expect(canSyncClassroomSnapshot(stage.id, { stage, scenes, generationComplete: false })).toBe(
      false,
    );
    expect(canSyncClassroomSnapshot('another', { stage, scenes, generationComplete: true })).toBe(
      false,
    );
    expect(canSyncClassroomSnapshot(stage.id, { stage, scenes: [], generationComplete: true })).toBe(
      false,
    );
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
