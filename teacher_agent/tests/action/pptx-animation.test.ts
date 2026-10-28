// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Action, PptxAnimationStep, Slide } from '@openmaic/dsl';
import { PptxAnimationPlayer, pptxAnimationFrames } from '@/lib/action/pptx-animation-player';
import {
  bindPptxAnimationsToActions,
  initialPlaybackHiddenElements,
  pptxParagraphKey,
} from '@/lib/import/pptx-animations';
import { useCanvasStore } from '@/lib/store/canvas';
import { resolveActionTimeline } from '@/lib/choreography/timeline';
import { ActionEngine } from '@/lib/action/engine';
import { PlaybackEngine } from '@/lib/playback/engine';
import type { AudioPlayer } from '@/lib/utils/audio-player';
import type { Scene } from '@/lib/types/stage';

const entrance: PptxAnimationStep = {
  id: 'original-1',
  trigger: 'click',
  effects: [
    { elementIds: ['principle'], effect: 'fade', phase: 'in', delayMs: 0, durationMs: 600 },
    {
      elementIds: ['example'],
      effect: 'fly',
      direction: 'left',
      phase: 'in',
      delayMs: 150,
      durationMs: 600,
    },
  ],
};
const exit: PptxAnimationStep = {
  id: 'original-2',
  trigger: 'click',
  effects: [
    { elementIds: ['principle'], effect: 'fade', phase: 'out', delayMs: 100, durationMs: 600 },
  ],
};
const slide = {
  id: 'canvas',
  elements: [{ id: 'principle' }, { id: 'example' }],
  pptxAnimation: { version: 1, steps: [entrance, exit], warnings: [] },
} as unknown as Slide;

describe('native PPTX animation and narration binding', () => {
  it('keeps source order, binds entrances before explanation and exits after it', () => {
    const speech: Action = {
      id: 'speech',
      type: 'speech',
      text: '这是原理。',
      audioId: 'already-generated',
    };
    const actions: Action[] = [
      { id: 'model-reveal', type: 'reveal', elementId: 'principle' },
      { id: 'focus', type: 'spotlight', elementId: 'principle' },
      speech,
      { id: 'example-focus', type: 'laser', elementId: 'example' },
      { id: 'speech-2', type: 'speech', text: '看这个例子。' },
    ];
    const result = bindPptxAnimationsToActions(actions, slide);
    expect(result.map((action) => action.id)).toEqual([
      'source-original-1',
      'focus',
      'speech',
      'source-original-2',
      'example-focus',
      'speech-2',
    ]);
    expect(result.find((action) => action.id === 'speech')).toBe(speech);
    expect(initialPlaybackHiddenElements(result)).toEqual(['principle', 'example']);
    expect(bindPptxAnimationsToActions(result, slide)).toEqual(result);
  });

  it('never hides an exit-only object or a whole-slide transition initially', () => {
    const actions: Action[] = [
      { id: 'exit', type: 'reveal', elementId: 'principle', pptxStep: exit },
      {
        id: 'transition',
        type: 'reveal',
        elementId: 'principle',
        pptxStep: {
          id: 'transition',
          trigger: 'auto',
          effects: [{ ...entrance.effects[0], scope: 'slide', elementIds: ['canvas'] }],
        },
      },
    ];
    expect(initialPlaybackHiddenElements(actions)).toEqual([]);
  });

  it('hides and builds individual paragraphs without hiding their shared textbox', () => {
    const native = {
      ...entrance,
      effects: [
        { ...entrance.effects[0], effect: 'box' as const, paragraphRange: { start: 1, end: 2 } },
      ],
    };
    const actions: Action[] = [
      { id: 'paragraph', type: 'reveal', elementId: 'principle', pptxStep: native },
    ];
    expect(initialPlaybackHiddenElements(actions)).toEqual([
      pptxParagraphKey('principle', 1),
      pptxParagraphKey('principle', 2),
    ]);
  });

  it('accounts for concurrent effects, original delay and playback speed', () => {
    const action: Action = {
      id: 'animation',
      type: 'reveal',
      elementId: 'principle',
      pptxStep: entrance,
    };
    expect(resolveActionTimeline([{ id: 'scene', actions: [action] } as never])[0].durationMs).toBe(
      750,
    );
    expect(
      resolveActionTimeline([{ id: 'scene', actions: [action] } as never], { playbackSpeed: 2 })[0]
        .durationMs,
    ).toBe(375);
  });

  it('leaves courses without imported animations unchanged', () => {
    const actions: Action[] = [{ id: 'normal', type: 'speech', text: '讲解' }];
    expect(bindPptxAnimationsToActions(actions, { ...slide, pptxAnimation: undefined })).toBe(
      actions,
    );
  });
});

describe('native PPTX playback clock', () => {
  let player: PptxAnimationPlayer;
  beforeEach(() => {
    vi.useFakeTimers();
    player = new PptxAnimationPlayer();
    useCanvasStore.getState().setHiddenElementIdList(['principle', 'example']);
    document.body.innerHTML =
      '<div id="screen-element-principle"><div>原理</div></div><div id="screen-element-example"><div>例子</div></div>';
    for (const node of document.body.children) {
      Object.defineProperty(node, 'animate', {
        value: vi.fn(() => ({ pause: vi.fn(), cancel: vi.fn(), currentTime: 0 })),
      });
    }
  });
  afterEach(() => {
    player.cancel();
    vi.useRealTimers();
    document.body.innerHTML = '';
  });

  it('respects delayed targets and actually supplies original effect frames to the DOM', async () => {
    const done = vi.fn();
    const playback = player.play(entrance).then(done);
    expect(useCanvasStore.getState().hiddenElementIdList).toEqual(['example']);
    await vi.advanceTimersByTimeAsync(144);
    expect(useCanvasStore.getState().hiddenElementIdList).toEqual(['example']);
    await vi.advanceTimersByTimeAsync(16);
    expect(useCanvasStore.getState().hiddenElementIdList).toEqual([]);
    const element = document.getElementById('screen-element-example')!;
    expect(element.animate).toHaveBeenCalledWith(
      [
        { transform: 'translate(-110%, 0)', opacity: 1 },
        { transform: 'translate(0, 0)', opacity: 1 },
      ],
      expect.objectContaining({ duration: 600 }),
    );
    await vi.advanceTimersByTimeAsync(590);
    await playback;
    expect(done).toHaveBeenCalledOnce();
  });

  it('freezes the entire group while paused, resumes it and applies exit state', async () => {
    const done = vi.fn();
    const playback = player.play(entrance).then(done);
    await vi.advanceTimersByTimeAsync(300);
    player.pause();
    await vi.advanceTimersByTimeAsync(2000);
    expect(done).not.toHaveBeenCalled();
    player.resume();
    await vi.advanceTimersByTimeAsync(450);
    await playback;
    const outgoing = player.play(exit);
    await vi.advanceTimersByTimeAsync(700);
    await outgoing;
    expect(useCanvasStore.getState().hiddenElementIdList).toEqual(['principle']);
  });

  it('finds targets when the new scene canvas mounts after playback has started', async () => {
    document.body.innerHTML = '';
    const playback = player.play(entrance);
    document.body.innerHTML = '<div id="screen-element-principle">new scene</div>';
    const node = document.getElementById('screen-element-principle')!;
    Object.defineProperty(node, 'animate', {
      value: vi.fn(() => ({ pause: vi.fn(), cancel: vi.fn(), currentTime: 0 })),
    });
    await vi.advanceTimersByTimeAsync(16);
    expect(node.animate).toHaveBeenCalledOnce();
    await vi.advanceTimersByTimeAsync(734);
    await playback;
    expect(useCanvasStore.getState().hiddenElementIdList).toEqual([]);
  });

  it('supports replay, cancellation, doubled speed and silent seeking', async () => {
    player.setRate(2);
    const playback = player.play(entrance);
    await vi.advanceTimersByTimeAsync(375);
    await playback;
    const outgoing = player.play(exit);
    player.cancel();
    await outgoing;
    await vi.advanceTimersByTimeAsync(1000);
    expect(useCanvasStore.getState().hiddenElementIdList).not.toContain('principle');
    await player.play(exit, true);
    expect(useCanvasStore.getState().hiddenElementIdList).toContain('principle');
    await player.play(entrance, true);
    expect(useCanvasStore.getState().hiddenElementIdList).toEqual([]);
    expect(player.active).toBe(false);
  });

  it('supports fade, appear, zoom and wipe entrance/exit frames', () => {
    for (const effect of ['appear', 'fade', 'zoom', 'wipe', 'box'] as const) {
      const source = { ...entrance.effects[0], effect };
      expect(pptxAnimationFrames({ ...source, phase: 'out' })).toEqual(
        [...pptxAnimationFrames(source)].reverse(),
      );
    }
  });

  it('animates only the specified paragraphs and leaves the rest of the text visible', async () => {
    document.getElementById('screen-element-principle')!.innerHTML =
      '<p data-pptx-paragraph="0">保持可见</p><p data-pptx-paragraph="1">逐段显示</p><p data-pptx-paragraph="2">保持可见</p>';
    const target = document.querySelector<HTMLElement>('[data-pptx-paragraph="1"]')!;
    Object.defineProperty(target, 'animate', {
      value: vi.fn(() => ({ pause: vi.fn(), cancel: vi.fn(), currentTime: 0 })),
    });
    useCanvasStore.getState().setHiddenElementIdList([pptxParagraphKey('principle', 1)]);
    const done = player.play({
      ...entrance,
      effects: [{ ...entrance.effects[0], effect: 'box', paragraphRange: { start: 1, end: 1 } }],
    });
    await vi.advanceTimersByTimeAsync(600);
    await done;
    expect(target.animate).toHaveBeenCalledOnce();
    expect(document.querySelector<HTMLElement>('[data-pptx-paragraph="0"]')!.style.visibility).toBe(
      '',
    );
    expect(useCanvasStore.getState().hiddenElementIdList).toEqual([]);
  });

  it('keeps the lecture cursor frozen while paused and advances to narration exactly once', async () => {
    const play = vi.fn(async () => true);
    const audio = {
      play,
      stop: vi.fn(),
      onEnded: vi.fn(),
      isPlaying: () => false,
      hasActiveAudio: () => false,
      getCurrentTime: () => 0,
      getDuration: () => 0,
    } as unknown as AudioPlayer;
    const actionEngine = new ActionEngine({} as never);
    const scene = {
      id: 'source-page',
      type: 'slide',
      content: { type: 'slide', canvas: {} },
      actions: [
        { id: 'native', type: 'reveal', elementId: 'principle', pptxStep: entrance },
        { id: 'narration', type: 'speech', text: '现在讲解原理。', audioId: 'voice' },
      ],
    } as unknown as Scene;
    const engine = new PlaybackEngine([scene], actionEngine, audio);
    engine.start();
    await vi.advanceTimersByTimeAsync(300);
    engine.pause();
    await vi.advanceTimersByTimeAsync(2000);
    expect(engine.getPlaybackPosition().elapsedMs).toBe(300);
    expect(play).not.toHaveBeenCalled();
    engine.resume();
    await vi.advanceTimersByTimeAsync(450);
    expect(play).toHaveBeenCalledOnce();
    engine.stop();
    actionEngine.dispose();
  });
});
