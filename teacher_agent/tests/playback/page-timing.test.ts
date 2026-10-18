import { afterEach, describe, expect, it, vi } from 'vitest';
import { PlaybackEngine } from '@/lib/playback/engine';
import { remainingPagePlayback, type PagePlaybackPosition } from '@/lib/playback/page-timing';
import type { Scene } from '@/lib/types/stage';
import type { Action } from '@/lib/types/action';
import type { ActionEngine } from '@/lib/action/engine';
import type { AudioPlayer } from '@/lib/utils/audio-player';

const scene = {
  id: 'page',
  stageId: 'stage',
  type: 'slide',
  title: 'Two real clips',
  order: 1,
  content: { type: 'slide', canvas: {} },
  actions: [
    { id: 'one', type: 'speech', text: '第一段讲解', audioId: 'audio-one' },
    { id: 'cue', type: 'spotlight', elementId: 'result' },
    { id: 'reveal', type: 'reveal', elementId: 'result', duration: 1000 },
    { id: 'two', type: 'speech', text: '第二段讲解', audioId: 'audio-two' },
  ],
} as unknown as Scene;
const durations = new Map([
  ['audio-one', 20_000],
  ['audio-two', 40_000],
]);
const position: PagePlaybackPosition = {
  actionIndex: 0,
  elapsedMs: 5000,
  audioDurationMs: 20_000,
  speechRemainingMs: null,
};

afterEach(() => vi.useRealTimers());

describe('remaining page playback', () => {
  it('does not assign planned waiting time to an activity with no narration', () => {
    expect(remainingPagePlayback({ ...scene, actions: [] }, position, durations, 1)).toEqual({
      seconds: 0,
      estimated: false,
    });
  });
  it('uses measured clips and reveal time without adding spotlight dwell or lesson-plan padding', () => {
    expect(remainingPagePlayback(scene, position, durations, 1)).toEqual({
      seconds: 56,
      estimated: false,
    });
  });
  it('seeks forward/backward using the action cursor, not previously elapsed wall time', () => {
    expect(
      remainingPagePlayback(
        scene,
        { ...position, actionIndex: 3, audioDurationMs: 40_000 },
        durations,
        1,
      ).seconds,
    ).toBe(35);
    expect(remainingPagePlayback(scene, { ...position, elapsedMs: 0 }, durations, 1).seconds).toBe(
      61,
    );
    expect(
      remainingPagePlayback(scene, { ...position, actionIndex: 4 }, durations, 1).seconds,
    ).toBe(0);
  });
  it('scales narration at 2x while reveal animation keeps its normal pace', () => {
    expect(
      remainingPagePlayback(scene, { ...position, elapsedMs: 2500 }, durations, 2).seconds,
    ).toBe(29);
  });
  it('uses the actual paused reading timer instead of recalculating the current line', () => {
    expect(
      remainingPagePlayback(scene, { ...position, speechRemainingMs: 7000 }, durations, 1).seconds,
    ).toBe(48);
  });
  it('marks missing narration as estimated and unknown video duration as unavailable', () => {
    expect(remainingPagePlayback(scene, position, new Map(), 1).estimated).toBe(true);
    const videoScene = {
      ...scene,
      actions: [{ id: 'video', type: 'play_video', elementId: 'video' } as Action],
    };
    expect(remainingPagePlayback(videoScene, position, durations, 1)).toEqual({
      seconds: null,
      estimated: true,
    });
  });
});

describe('engine clock source', () => {
  function setup(playResult = true) {
    let time = 0;
    let active = false;
    let ended = () => {};
    let speed = 1;
    const audio = {
      play: vi.fn(async () => {
        active = playResult;
        time = 0;
        return playResult;
      }),
      getCurrentTime: () => time,
      getDuration: () => 20_000,
      hasActiveAudio: () => active,
      isPlaying: () => active,
      onEnded: (callback: () => void) => {
        ended = callback;
      },
      pause: vi.fn(),
      resume: vi.fn(),
      stop: () => {
        active = false;
        time = 0;
      },
    } as unknown as AudioPlayer;
    const actionEngine = {
      execute: vi.fn(async () => {}),
      clearEffects: vi.fn(),
      resetPlaybackVisualState: vi.fn(),
    } as unknown as ActionEngine;
    const engine = new PlaybackEngine([scene], actionEngine, audio, {
      getPlaybackSpeed: () => speed,
    });
    return {
      engine,
      setTime: (value: number) => {
        time = value;
      },
      setSpeed: (value: number) => {
        speed = value;
      },
      ended: () => ended(),
    };
  }
  it('does not consume audio time during loading, buffering or pause, and follows media seeks and speed', async () => {
    vi.useFakeTimers();
    const { engine, setTime, setSpeed } = setup();
    engine.start();
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(engine.getPlaybackPosition().elapsedMs).toBe(0);
    setTime(6000);
    expect(engine.getPlaybackPosition().elapsedMs).toBe(6000);
    engine.pause();
    await vi.advanceTimersByTimeAsync(30_000);
    expect(engine.getPlaybackPosition().elapsedMs).toBe(6000);
    setTime(15_000);
    setSpeed(2);
    expect(engine.getPlaybackPosition().elapsedMs).toBe(7500);
    await engine.jumpToAction(3, { autoplay: false });
    expect(engine.getPlaybackPosition()).toMatchObject({ actionIndex: 3, elapsedMs: 0 });
    engine.stop();
    expect(engine.getPlaybackPosition()).toMatchObject({ actionIndex: 0, elapsedMs: 0 });
  });
  it('freezes silent reading time on pause and resumes its remaining duration', async () => {
    vi.useFakeTimers();
    const { engine } = setup(false);
    engine.start();
    await vi.advanceTimersByTimeAsync(500);
    const before = engine.getPlaybackPosition().speechRemainingMs;
    expect(before).toBeGreaterThan(0);
    engine.pause();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(engine.getPlaybackPosition().speechRemainingMs).toBe(before);
    engine.resume();
    await vi.advanceTimersByTimeAsync(200);
    expect(engine.getPlaybackPosition().speechRemainingMs).toBe(before! - 200);
    engine.stop();
  });
});
