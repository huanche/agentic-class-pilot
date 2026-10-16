import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { PlaybackEngine } from '@/lib/playback/engine';
import { ActionEngine } from '@/lib/action/engine';
import { useCanvasStore } from '@/lib/store/canvas';
import type { Action } from '@/lib/types/action';
import type { Scene } from '@/lib/types/stage';
import type { AudioPlayer } from '@/lib/utils/audio-player';

function setup(actions: Action[]) {
  let ended: () => void = () => {};
  const player = {
    play: vi.fn().mockResolvedValue(true),
    onEnded: vi.fn((fn: () => void) => {
      ended = fn;
    }),
    stop: vi.fn(),
    pause: vi.fn(),
    resume: vi.fn(),
    isPlaying: () => true,
    hasActiveAudio: () => true,
  } as unknown as AudioPlayer;
  const scene = {
    id: 's',
    stageId: 'course',
    order: 1,
    type: 'slide',
    title: 'Python',
    content: {
      type: 'slide',
      canvas: {
        elements: [
          { id: 'office', type: 'text', content: '<p>办公自动化：批量整理文件、合并表格</p>' },
          { id: 'data', type: 'text', content: '<p>数据分析：清洗数据、看趋势画图</p>' },
        ],
      },
    },
    actions,
  } as unknown as Scene;
  const actionEngine = new ActionEngine({} as never);
  const onComplete = vi.fn();
  const engine = new PlaybackEngine([scene], actionEngine, player, { onComplete });
  return { engine, actionEngine, end: () => ended(), onComplete, scene, player };
}
const speech = (id: string, text: string): Action => ({
  id,
  type: 'speech',
  text,
  audioId: `audio-${id}`,
});

describe('focus follows actual speech playback', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    useCanvasStore.getState().clearAllEffects();
  });
  afterEach(() => {
    vi.useRealTimers();
    useCanvasStore.getState().clearAllEffects();
  });

  it('holds focus beyond five seconds, clears at audio end, and does not leak into an uncued line', async () => {
    const fixture = setup([
      { id: 'f', type: 'spotlight', elementId: 'office' },
      speech('a', '办公自动化可以批量整理文件并合并表格。'),
      speech('b', '下面进入下一部分。'),
    ]);
    fixture.engine.start();
    await vi.advanceTimersByTimeAsync(12_000);
    expect(useCanvasStore.getState().spotlightElementId).toBe('office');
    fixture.end();
    expect(useCanvasStore.getState().spotlightElementId).toBe('');
    fixture.engine.stop();
    fixture.actionEngine.dispose();
  });

  it('plays the authored binding without guessing a new target or editing speech/audio ids', async () => {
    const actions = [
      { id: 'f', type: 'spotlight', elementId: 'office' },
      speech('a', '数据分析需要清洗数据，再把趋势画图展示出来。'),
    ] as Action[];
    const original = JSON.stringify(actions);
    const fixture = setup(actions);
    fixture.engine.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(useCanvasStore.getState().spotlightElementId).toBe('office');
    expect(JSON.stringify(actions)).toBe(original);
    expect(fixture.player.play).toHaveBeenCalledWith('audio-a', undefined);
    fixture.engine.stop();
    fixture.actionEngine.dispose();
  });

  it('restores the paired focus when jumping directly to a speech action', async () => {
    const fixture = setup([
      { id: 'f', type: 'spotlight', elementId: 'office' },
      speech('a', '办公自动化可以批量整理文件并合并表格。'),
    ]);
    await fixture.engine.jumpToAction(1, { autoplay: true });
    await vi.advanceTimersByTimeAsync(6_000);
    expect(useCanvasStore.getState().spotlightElementId).toBe('office');
    fixture.engine.stop();
    fixture.actionEngine.dispose();
  });

  it('keeps the same focus through pause/resume and removes it when the resumed audio ends', async () => {
    const fixture = setup([
      { id: 'f', type: 'laser', elementId: 'office' },
      speech('a', '办公自动化可以批量整理文件并合并表格。'),
      speech('b', '继续讲解。'),
    ]);
    fixture.engine.start();
    await vi.advanceTimersByTimeAsync(1000);
    fixture.engine.pause();
    await vi.advanceTimersByTimeAsync(6000);
    expect(useCanvasStore.getState().laserElementId).toBe('office');
    fixture.engine.resume();
    fixture.end();
    expect(useCanvasStore.getState().laserElementId).toBe('');
    fixture.engine.stop();
    fixture.actionEngine.dispose();
  });

  it('keeps the standalone live-action timer unchanged', async () => {
    const actionEngine = new ActionEngine({} as never);
    await actionEngine.execute({ id: 'f', type: 'spotlight', elementId: 'office' });
    await vi.advanceTimersByTimeAsync(4999);
    expect(useCanvasStore.getState().spotlightElementId).toBe('office');
    await vi.advanceTimersByTimeAsync(1);
    expect(useCanvasStore.getState().spotlightElementId).toBe('');
    actionEngine.dispose();
  });
});
