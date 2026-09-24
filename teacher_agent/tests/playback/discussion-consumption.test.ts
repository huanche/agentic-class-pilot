import { describe, expect, it, vi } from 'vitest';

import { PlaybackEngine } from '@/lib/playback/engine';
import type { Action } from '@/lib/types/action';
import type { Scene } from '@/lib/types/stage';
import type { ActionEngine } from '@/lib/action/engine';
import type { AudioPlayer } from '@/lib/utils/audio-player';

function scene(actions: Action[]): Scene {
  return {
    id: 'scene-1',
    stageId: 'stage-1',
    type: 'slide',
    title: 'Scene 1',
    order: 1,
    content: { type: 'slide', canvas: {} },
    actions,
  } as unknown as Scene;
}

describe('legacy classroom discussion actions', () => {
  it('skips the old cue and completes without starting a live discussion', async () => {
    const onProactiveShow = vi.fn();
    const onDiscussionConfirmed = vi.fn();
    const onComplete = vi.fn();
    const actionEngine = {
      execute: vi.fn(async () => {}),
      clearEffects: vi.fn(),
      resetPlaybackVisualState: vi.fn(),
    } as unknown as ActionEngine;
    const audioPlayer = {
      play: vi.fn(async () => false),
      onEnded: vi.fn(),
      stop: vi.fn(),
      pause: vi.fn(),
      resume: vi.fn(),
      isPlaying: vi.fn(() => false),
      hasActiveAudio: vi.fn(() => false),
    } as unknown as AudioPlayer;
    const engine = new PlaybackEngine(
      [scene([{ id: 'old-discussion', type: 'discussion', topic: 'Old topic' } as Action])],
      actionEngine,
      audioPlayer,
      { onProactiveShow, onDiscussionConfirmed, onComplete },
    );

    engine.start();
    await new Promise<void>((resolve) => setTimeout(resolve, 0));

    expect(onProactiveShow).not.toHaveBeenCalled();
    expect(onDiscussionConfirmed).not.toHaveBeenCalled();
    expect(onComplete).toHaveBeenCalledOnce();
    expect(engine.isExhausted()).toBe(true);
  });
});
