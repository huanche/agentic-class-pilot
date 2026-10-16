import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AudioPlayer } from '@/lib/utils/audio-player';
import { PlaybackEngine } from '@/lib/playback/engine';
import { ActionEngine } from '@/lib/action/engine';
import { useCanvasStore } from '@/lib/store/canvas';
import type { Scene } from '@/lib/types/stage';

vi.mock('@/lib/media/resolve-audio-bytes', () => ({
  resolveAudioBlob: async () => new Blob(['audio']),
}));
const media: Media[] = [];
class Media extends EventTarget {
  ended = false;
  paused = true;
  currentTime = 0;
  duration = 6;
  volume = 1;
  playbackRate = 1;
  defaultPlaybackRate = 1;
  src = '';
  constructor() {
    super();
    media.push(this);
  }
  play = vi.fn(async () => {
    if (this.ended) {
      this.ended = false;
      this.currentTime = 0;
    }
    this.paused = false;
  });
  pause = vi.fn(() => {
    this.paused = true;
  });
  finish() {
    this.ended = true;
    this.paused = true;
    this.currentTime = this.duration;
    this.dispatchEvent(new Event('ended'));
  }
}
describe('ended narration is not resumable', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    media.length = 0;
    vi.stubGlobal('Audio', Media);
    vi.stubGlobal(
      'URL',
      Object.assign(class extends URL {}, {
        createObjectURL: () => 'blob:test',
        revokeObjectURL: vi.fn(),
      }),
    );
    useCanvasStore.getState().clearAllEffects();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });
  it('keeps paused speech resumable but never restarts an ended audio element', async () => {
    const player = new AudioPlayer();
    await player.play('first');
    player.pause();
    expect(player.hasActiveAudio()).toBe(true);
    player.resume();
    expect(media[0].play).toHaveBeenCalledTimes(2);
    media[0].finish();
    expect(player.hasActiveAudio()).toBe(false);
    player.resume();
    expect(media[0].play).toHaveBeenCalledTimes(2);
    player.stop();
  });
  it('moves to the correct focused speech when paused between audio end and reveal completion', async () => {
    const scene = {
      id: 'scene',
      stageId: 'stage',
      type: 'slide',
      order: 1,
      title: 'Examples',
      content: { type: 'slide', canvas: { elements: [] } },
      actions: [
        { id: 'f1', type: 'spotlight', elementId: 'example' },
        { id: 's1', type: 'speech', text: '先讲示例。', audioId: 'first' },
        { id: 'r', type: 'reveal', elementId: 'conclusion', duration: 520 },
        { id: 'f2', type: 'spotlight', elementId: 'conclusion' },
        { id: 's2', type: 'speech', text: '再讲结论。', audioId: 'second' },
      ],
    } as unknown as Scene;
    const player = new AudioPlayer();
    const effects = new ActionEngine({} as never);
    const onSpeechStart = vi.fn();
    const engine = new PlaybackEngine([scene], effects, player, { onSpeechStart });
    engine.start();
    await vi.advanceTimersByTimeAsync(0);
    media[0].finish();
    engine.pause();
    await vi.advanceTimersByTimeAsync(200);
    engine.resume();
    await vi.advanceTimersByTimeAsync(0);
    expect(media).toHaveLength(2);
    expect(media[0].play).toHaveBeenCalledOnce();
    expect(useCanvasStore.getState().spotlightElementId).toBe('conclusion');
    expect(onSpeechStart.mock.calls.map((c) => c[0])).toEqual(['先讲示例。', '再讲结论。']);
    await vi.advanceTimersByTimeAsync(1000);
    expect(media).toHaveLength(2);
    engine.stop();
    effects.dispose();
  });
});
