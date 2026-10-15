import { describe, expect, it, vi } from 'vitest';
import { PlaybackEngine } from '@/lib/playback/engine';
import type { ActionEngine } from '@/lib/action/engine';
import type { AudioPlayer } from '@/lib/utils/audio-player';
import type { Scene } from '@/lib/types/stage';

describe('pause while narration is loading', () => {
  it('cancels the pending audio and resumes the same sentence', async () => {
    let resolveFirst!: (started: boolean) => void;
    const audio = {
      play: vi
        .fn()
        .mockImplementationOnce(
          () =>
            new Promise<boolean>((resolve) => {
              resolveFirst = resolve;
            }),
        )
        .mockResolvedValue(true),
      onEnded: vi.fn(),
      stop: vi.fn(),
      pause: vi.fn(),
      resume: vi.fn(),
      isPlaying: vi.fn(() => false),
      hasActiveAudio: vi.fn(() => false),
    };
    const scene = {
      id: 'scene',
      stageId: 'stage',
      type: 'slide',
      actions: [
        { id: 'a', type: 'speech', text: '第一句还在加载', audioId: 'audio-a' },
        { id: 'b', type: 'speech', text: '第二句', audioId: 'audio-b' },
      ],
    } as unknown as Scene;
    const engine = new PlaybackEngine(
      [scene],
      {
        execute: vi.fn(),
        clearEffects: vi.fn(),
        resetPlaybackVisualState: vi.fn(),
      } as unknown as ActionEngine,
      audio as unknown as AudioPlayer,
    );
    engine.start();
    expect(audio.play).toHaveBeenCalledWith('audio-a', undefined);
    engine.pause();
    expect(audio.pause).toHaveBeenCalledOnce();
    resolveFirst(false);
    await Promise.resolve();
    engine.resume();
    expect(audio.play).toHaveBeenNthCalledWith(2, 'audio-a', undefined);
    expect(engine.getMode()).toBe('playing');
    engine.stop();
  });
});
