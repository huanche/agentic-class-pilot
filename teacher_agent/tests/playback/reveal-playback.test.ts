import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ActionEngine } from '@/lib/action/engine';
import { PlaybackEngine } from '@/lib/playback/engine';
import { useCanvasStore } from '@/lib/store/canvas';
import type { Scene } from '@/lib/types/stage';
import type { AudioPlayer } from '@/lib/utils/audio-player';

describe('slide reveal during sequential playback', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    useCanvasStore.getState().setHiddenElementIdList(['conclusion', 'later']);
    useCanvasStore.getState().setRevealedElementIdList([]);
  });

  afterEach(() => {
    vi.useRealTimers();
    useCanvasStore.getState().setHiddenElementIdList([]);
    useCanvasStore.getState().setRevealedElementIdList([]);
  });

  function buildEngine() {
    const onComplete = vi.fn();
    const actionEngine = new ActionEngine({} as never);
    const scene = {
      id: 'scene-1',
      stageId: 'stage-1',
      type: 'slide',
      title: 'Reveal conclusion',
      order: 1,
      content: { type: 'slide', canvas: {} },
      actions: [{ id: 'reveal-1', type: 'reveal', elementId: 'conclusion', duration: 520 }],
    } as unknown as Scene;
    const audioPlayer = { stop: vi.fn() } as unknown as AudioPlayer;
    const engine = new PlaybackEngine([scene], actionEngine, audioPlayer, { onComplete });
    return { engine, actionEngine, onComplete };
  }

  it('shows the target and waits for its entrance before completing the scene', async () => {
    const { engine, actionEngine, onComplete } = buildEngine();
    engine.start();

    expect(useCanvasStore.getState().hiddenElementIdList).toEqual(['later']);
    expect(useCanvasStore.getState().revealedElementIdList).toContain('conclusion');
    expect(onComplete).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(519);
    expect(onComplete).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(onComplete).toHaveBeenCalledOnce();
    expect(engine.getMode()).toBe('idle');
    actionEngine.dispose();
  });

  it('does not resume a stopped lesson when the entrance finishes', async () => {
    const { engine, actionEngine, onComplete } = buildEngine();
    engine.start();
    engine.stop();
    await vi.advanceTimersByTimeAsync(520);

    expect(onComplete).not.toHaveBeenCalled();
    expect(engine.getMode()).toBe('idle');
    actionEngine.dispose();
  });
});
