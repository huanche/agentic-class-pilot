import { describe, expect, it, vi } from 'vitest';
import type { Scene, ScenePatch } from '@/lib/types/stage';
import { prepareRegeneratedAudio } from '@/lib/agent/client/prepare-regenerated-audio';

const scene = () =>
  ({
    id: 's',
    stageId: 'class',
    order: 4,
    type: 'slide',
    title: 'C语言',
    content: { type: 'slide', canvas: { elements: [] } },
    actions: [{ type: 'speech', id: 'old', text: '旧讲解', audioId: 'old-audio' }],
    timing: { plannedDurationSec: 60, measuredDurationSec: 44, measurementKey: 'old' },
  }) as unknown as Scene;
const patch = (): ScenePatch => ({
  actions: [{ type: 'speech', id: 'new', text: '新讲解', audioInvalidated: true }],
});
function dependencies() {
  return {
    enabled: true,
    providerId: 'kokoro',
    language: '中文',
    dispose: vi.fn(async () => {}),
    generate: vi.fn(async (candidate: Scene) => {
      for (const action of candidate.actions ?? [])
        if (action.type === 'speech') {
          action.audioId = 'new-audio';
          delete action.audioInvalidated;
        }
      candidate.timing = { ...candidate.timing, measuredDurationSec: 55, measurementKey: 'new' };
      return { success: true, failedCount: 0 };
    }),
  };
}
describe('regenerated page narration', () => {
  it('generates audio and measured timing before returning the patch, preserving the old page', async () => {
    const old = scene();
    const proposed = patch();
    const deps = dependencies();
    const result = await prepareRegeneratedAudio(old, proposed, deps);
    expect(deps.generate).toHaveBeenCalledWith(
      expect.objectContaining({ id: 's', stageId: 'class', order: 4 }),
      '中文',
      undefined,
    );
    expect(result.actions?.[0]).toMatchObject({ audioId: 'new-audio', text: '新讲解' });
    expect(result.timing).toMatchObject({ measuredDurationSec: 55, plannedDurationSec: 60 });
    expect(old.actions?.[0]).toMatchObject({ audioId: 'old-audio' });
    expect(proposed.actions?.[0]).not.toHaveProperty('audioId');
  });
  it.each([false, 'browser-native-tts'])(
    'respects explicitly disabled or browser-native TTS: %s',
    async (mode) => {
      const deps = dependencies();
      if (typeof mode === 'string') deps.providerId = mode;
      else deps.enabled = mode;
      const result = await prepareRegeneratedAudio(scene(), patch(), deps);
      expect(deps.generate).not.toHaveBeenCalled();
      expect(result.timing?.measuredDurationSec).toBeUndefined();
    },
  );
  it('rejects a provider that silently skips speech generation', async () => {
    const deps = dependencies();
    deps.generate.mockImplementation(async () => ({ success: true, failedCount: 0 }));
    await expect(prepareRegeneratedAudio(scene(), patch(), deps)).rejects.toThrow('配音生成失败');
  });
  it('discards partial audio and does not return a silent replacement on failure', async () => {
    const deps = dependencies();
    deps.generate.mockImplementation(async (candidate) => {
      const action = candidate.actions![0];
      if (action.type === 'speech') action.audioId = 'partial';
      return { success: false, failedCount: 1 };
    });
    await expect(prepareRegeneratedAudio(scene(), patch(), deps)).rejects.toThrow('配音生成失败');
    expect(deps.dispose).toHaveBeenCalledWith(['partial']);
  });
  it('rejects a stale page and cleans its newly generated audio', async () => {
    const deps = { ...dependencies(), isCurrent: () => false };
    await expect(prepareRegeneratedAudio(scene(), patch(), deps)).rejects.toThrow('本页发生了变化');
    expect(deps.dispose).toHaveBeenCalledWith(['new-audio']);
  });
  it('honors cancellation before invoking TTS', async () => {
    const deps = dependencies();
    const abort = new AbortController();
    abort.abort();
    await expect(
      prepareRegeneratedAudio(scene(), patch(), { ...deps, signal: abort.signal }),
    ).rejects.toThrow();
    expect(deps.generate).not.toHaveBeenCalled();
  });
});
