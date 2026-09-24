import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ActionEngine } from '@/lib/action/engine';
import { useCanvasStore } from '@/lib/store/canvas';

describe('slide reveal action', () => {
  beforeEach(() => {
    useCanvasStore.getState().setHiddenElementIdList(['conclusion']);
    useCanvasStore.getState().setRevealedElementIdList([]);
  });

  it('reveals the target on the timeline and waits for the entrance animation', async () => {
    vi.useFakeTimers();
    const engine = new ActionEngine({} as never);
    const execution = engine.execute({
      id: 'reveal-1',
      type: 'reveal',
      elementId: 'conclusion',
      effect: 'fade-up',
      duration: 520,
    });

    expect(useCanvasStore.getState().hiddenElementIdList).not.toContain('conclusion');
    expect(useCanvasStore.getState().revealedElementIdList).toContain('conclusion');
    await vi.advanceTimersByTimeAsync(520);
    await execution;
    vi.useRealTimers();
  });
});
