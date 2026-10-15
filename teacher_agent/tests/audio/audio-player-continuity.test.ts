import { afterEach, expect, it, vi } from 'vitest';
const bytes = vi.hoisted(() => vi.fn(async (): Promise<Blob | null> => new Blob(['audio'])));
vi.mock('@/lib/media/resolve-audio-bytes', () => ({ resolveAudioBlob: bytes }));
import { AudioPlayer } from '@/lib/utils/audio-player';
afterEach(() => {
  vi.unstubAllGlobals();
  bytes.mockReset();
});

it('reuses the unlocked element across sentences and pages, ignoring stale ended callbacks', async () => {
  const instances: AudioStub[] = [];
  class AudioStub {
    src = '';
    currentTime = 0;
    paused = true;
    listeners: Array<() => void> = [];
    constructor() {
      instances.push(this);
    }
    play = async () => {
      this.paused = false;
    };
    pause = () => {
      this.paused = true;
    };
    addEventListener = (_type: string, callback: () => void) => {
      this.listeners.push(callback);
    };
    removeEventListener = vi.fn();
  }
  vi.stubGlobal('Audio', AudioStub);
  const player = new AudioPlayer();
  const ended = vi.fn();
  player.onEnded(ended);
  await player.play('first');
  const staleEnd = instances[0].listeners[0];
  player.stop();
  await player.play('second');
  expect(instances).toHaveLength(1);
  staleEnd();
  expect(ended).not.toHaveBeenCalled();
  player.pause();
  player.resume();
  instances[0].listeners[1]();
  expect(ended).toHaveBeenCalledTimes(1);
  expect(player.hasActiveAudio()).toBe(false);
  player.destroy();
});

it('pause aborts a pending narration fetch and never starts audio later', async () => {
  bytes.mockResolvedValue(null);
  let signal: AbortSignal | null = null;
  vi.stubGlobal(
    'fetch',
    vi.fn(
      (_url, options) =>
        new Promise((_resolve, reject) => {
          signal = options.signal;
          signal!.addEventListener('abort', () => reject(new Error('aborted')));
        }),
    ),
  );
  const Audio = vi.fn();
  vi.stubGlobal('Audio', Audio);
  const player = new AudioPlayer();
  const pending = player.play('first', 'https://example.test/audio.mp3');
  await vi.waitFor(() => expect(signal).not.toBeNull());
  player.pause();
  await expect(pending).resolves.toBe(false);
  expect(Audio).not.toHaveBeenCalled();
});
