// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest';
import { ActionEngine } from '@/lib/action/engine';
import { nativePptxPage, registerNativeDriver } from '@/lib/onlyoffice/native-player';
import type { Stage, Scene } from '@/lib/types/stage';
import type { StageStore } from '@/lib/api/stage-api';
import { bindNativePptxActions } from '@/lib/onlyoffice/narration';
import { initialPlaybackHiddenElements } from '@/lib/import/pptx-animations';
import type { Slide, Action } from '@openmaic/dsl';
import { PlaybackEngine } from '@/lib/playback/engine';
import type { AudioPlayer } from '@/lib/utils/audio-player';

describe('ONLYOFFICE playback in the formal action engine', () => {
  it('does not start a static page narration while its source is loading or after a pending start was paused', async () => {
    const scene = {
      id: 'native_static',
      stageId: 'native_static_stage',
      outlineId: 'static',
      type: 'slide',
      actions: [{ id: 'speech', type: 'speech', text: '静态原稿也要先显示', audioId: 'voice' }],
    } as Scene;
    const stage = {
      id: 'native_static_stage',
      nativePptx: { pages: { static: 1 } },
    } as unknown as Stage;
    const store = {
      getState: () => ({ stage, scenes: [scene], currentSceneId: scene.id, mode: 'playback' }),
      setState: vi.fn(),
      subscribe: vi.fn(),
    } as unknown as StageStore;
    let resolve!: () => void;
    const driver = {
      ready: new Promise<void>((r) => {
        resolve = r;
      }),
      seek: vi.fn(async () => {}),
      pause: vi.fn(),
      resume: vi.fn(),
      reset: vi.fn(),
    };
    const unregister = registerNativeDriver(scene.id, driver);
    const audio = {
      play: vi.fn(async () => true),
      stop: vi.fn(),
      onEnded: vi.fn(),
      isPlaying: () => false,
      hasActiveAudio: () => false,
      getCurrentTime: () => 0,
      getDuration: () => 0,
    } as unknown as AudioPlayer;
    const actionEngine = new ActionEngine(store);
    const player = new PlaybackEngine([scene], actionEngine, audio);
    try {
      player.start();
      expect(audio.play).not.toHaveBeenCalled();
      player.pause();
      resolve();
      await Promise.resolve();
      await Promise.resolve();
      expect(audio.play).not.toHaveBeenCalled();
      player.resume();
      await vi.waitFor(() => expect(audio.play).toHaveBeenCalledOnce());
    } finally {
      player.stop();
      actionEngine.dispose();
      unregister();
    }
  });
  it('waits for native readiness, advances the source click once, and preserves pause/resume/reset', async () => {
    const animation = {
      id: 'click1',
      type: 'reveal' as const,
      elementId: 'a',
      pptxStep: {
        id: 'source1',
        trigger: 'click' as const,
        effects: [
          {
            elementIds: ['a'],
            effect: 'fade' as const,
            phase: 'in' as const,
            delayMs: 0,
            durationMs: 200,
          },
        ],
      },
    };
    const stage = {
      id: 'native_stage',
      nativePptx: { pages: { original8: 8 } },
    } as unknown as Stage;
    const scene = {
      id: 'native_scene',
      outlineId: 'original8',
      type: 'slide',
      actions: [animation],
    } as unknown as Scene;
    const state = { stage, scenes: [scene], currentSceneId: scene.id, mode: 'playback' };
    const store = {
      getState: () => state,
      setState: vi.fn(),
      subscribe: vi.fn(),
    } as unknown as StageStore;
    let ready!: () => void;
    const driver = {
      ready: new Promise<void>((resolve) => {
        ready = resolve;
      }),
      seek: vi.fn(async () => {}),
      pause: vi.fn(),
      resume: vi.fn(),
      reset: vi.fn(),
    };
    const unregister = registerNativeDriver(scene.id, driver);
    const engine = new ActionEngine(store);
    try {
      const action = engine.execute(animation);
      await Promise.resolve();
      expect(driver.seek).not.toHaveBeenCalled();
      ready();
      await action;
      expect(driver.seek).toHaveBeenCalledExactlyOnceWith(1);
      engine.pauseSourceAnimation();
      engine.resumeSourceAnimation();
      engine.cancelSourceAnimation();
      expect(driver.pause).toHaveBeenCalledOnce();
      expect(driver.resume).toHaveBeenCalledOnce();
      expect(driver.reset).toHaveBeenCalledOnce();
      expect(nativePptxPage(stage, { ...scene, nativePptxEdited: true })).toBeUndefined();
      expect(nativePptxPage(stage, scene)).toBe(8);
    } finally {
      unregister();
      engine.dispose();
    }
  });
  it('uses stable source identity when pages are deleted or reordered', () => {
    const stage = { nativePptx: { pages: { second: 9, first: 5 } } } as unknown as Stage;
    expect(
      nativePptxPage(stage, {
        id: 'order1',
        type: 'slide',
        outlineId: 'second',
        order: 1,
      } as Scene),
    ).toBe(9);
    expect(
      nativePptxPage(stage, { id: 'order2', type: 'slide', outlineId: 'first', order: 2 } as Scene),
    ).toBe(5);
    expect(
      nativePptxPage(stage, { id: 'new', type: 'slide', outlineId: 'new' } as Scene),
    ).toBeUndefined();
  });
  it('retains clicks unsupported by the old importer without losing the legacy fallback effects', () => {
    const legacy = {
      id: 'pptx-step-5',
      trigger: 'click',
      effects: [
        { elementIds: ['legacy'], effect: 'fade', phase: 'in', delayMs: 0, durationMs: 500 },
      ],
    };
    const slide = {
      id: 'canvas',
      elements: [{ id: 'legacy' }],
      pptxAnimation: { steps: [legacy] },
    } as unknown as Slide;
    const clicks = [1, 2, 3].map((i) => ({
      id: `onlyoffice-click-${i}`,
      durationMs: 500,
      sourceEffectIds: [String(i === 2 ? 5 : i + 10)],
      description: 'source',
    }));
    const speeches = [1, 2, 3].map((i) => ({
      id: `speech${i}`,
      type: 'speech',
      text: '独立解释',
    })) as Action[];
    const result = bindNativePptxActions(speeches, slide, clicks);
    expect(
      result.filter((a) => a.type === 'reveal' && a.pptxStep?.id.startsWith('onlyoffice-click-')),
    ).toHaveLength(3);
    expect(result.map((a) => a.id)).toEqual([
      'source-onlyoffice-click-1',
      'speech1',
      'source-onlyoffice-click-2',
      'legacy-pptx-step-5',
      'speech2',
      'source-onlyoffice-click-3',
      'speech3',
    ]);
    expect(initialPlaybackHiddenElements(result)).toEqual(['legacy']);
    expect(() => bindNativePptxActions(speeches.slice(0, 1), slide, clicks)).toThrow(
      '原稿有 3 次点击',
    );
  });
});
