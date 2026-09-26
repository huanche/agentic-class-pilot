import { describe, expect, it, vi } from 'vitest';

import { PlaybackEngine } from '@/lib/playback/engine';
import type { Action, SpeechAction } from '@/lib/types/action';
import type { Scene } from '@/lib/types/stage';
import type { ActionEngine } from '@/lib/action/engine';
import type { AudioPlayer } from '@/lib/utils/audio-player';

function speechScene(): Scene {
  return {
    id: 'scene-1',
    stageId: 'stage-1',
    type: 'slide',
    title: 'Scene 1',
    order: 1,
    content: { type: 'slide', canvas: {} },
    actions: [
      { id: 'line-1', type: 'speech', text: '第一句配音', audioId: 'ast_line1' },
      { id: 'line-2', type: 'speech', text: '第二句配音', audioId: 'ast_line2' },
    ] as unknown as Action[],
  } as unknown as Scene;
}

function notAllowedError(): Error {
  return Object.assign(new Error('play() failed because the user did not interact'), {
    name: 'NotAllowedError',
  });
}

function buildEngine(play: ReturnType<typeof vi.fn>, callbacks: Record<string, unknown> = {}) {
  const actionEngine = {
    execute: vi.fn(async () => {}),
    clearEffects: vi.fn(),
    resetPlaybackVisualState: vi.fn(),
  } as unknown as ActionEngine;
  const audioPlayer = {
    play,
    onEnded: vi.fn(),
    stop: vi.fn(),
    pause: vi.fn(),
    resume: vi.fn(),
    isPlaying: vi.fn(() => false),
    hasActiveAudio: vi.fn(() => false),
  } as unknown as AudioPlayer;
  return new PlaybackEngine([speechScene()], actionEngine, audioPlayer, callbacks);
}

const flush = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

describe('autoplay-blocked narration parking and recovery', () => {
  it('parks on the blocked line and replays it after the unlock click', async () => {
    const play = vi
      .fn<(audioId: string, legacyUrl?: string) => Promise<boolean>>()
      .mockRejectedValueOnce(notAllowedError())
      .mockResolvedValueOnce(true);
    const onAudioBlocked = vi.fn();
    const onAudioUnblocked = vi.fn();
    const engine = buildEngine(play as never, { onAudioBlocked, onAudioUnblocked });

    engine.start();
    await flush();
    await flush();

    // Parked: blocked callback fired, the line was NOT skipped (play called
    // once, nothing advanced past it).
    expect(onAudioBlocked).toHaveBeenCalledOnce();
    expect(play).toHaveBeenCalledExactlyOnceWith('ast_line1', undefined);

    // The in-frame click retries the SAME line.
    engine.retryBlockedAudio();
    await flush();
    await flush();

    expect(play).toHaveBeenCalledTimes(2);
    expect(play).toHaveBeenNthCalledWith(2, 'ast_line1', undefined);
    expect(onAudioUnblocked).toHaveBeenCalledOnce();
    expect(engine.getCurrentSceneId()).toBe('scene-1');
  });

  it('retry is a no-op when nothing is blocked', async () => {
    const play = vi.fn().mockResolvedValue(true);
    const onAudioBlocked = vi.fn();
    const engine = buildEngine(play as never, { onAudioBlocked });

    engine.retryBlockedAudio();
    await flush();

    expect(onAudioBlocked).not.toHaveBeenCalled();
    expect(play).not.toHaveBeenCalled();
  });

  it('a non-policy playback error keeps the silent reading-timer fallback', async () => {
    vi.useFakeTimers();
    try {
      const play = vi.fn().mockRejectedValue(new Error('decode failed'));
      const onComplete = vi.fn();
      const onAudioBlocked = vi.fn();
      const engine = buildEngine(play as never, { onComplete, onAudioBlocked });

      engine.start();
      await vi.advanceTimersByTimeAsync(0);
      // Blocked callback must not fire for an ordinary error; the reading
      // timer (2s floor per line) advances the lesson instead.
      expect(onAudioBlocked).not.toHaveBeenCalled();
      await vi.advanceTimersByTimeAsync(10_000);
      expect(onComplete).toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it('clears the blocked state on stop so the overlay cannot linger', async () => {
    const play = vi.fn().mockRejectedValueOnce(notAllowedError()).mockResolvedValue(true);
    const onAudioUnblocked = vi.fn();
    const engine = buildEngine(play as never, { onAudioUnblocked });

    engine.start();
    await flush();
    await flush();

    engine.stop();
    expect(onAudioUnblocked).toHaveBeenCalledOnce();

    // After stop, retry must not resurrect playback.
    engine.retryBlockedAudio();
    await flush();
    expect(play).toHaveBeenCalledTimes(1);
  });
});
