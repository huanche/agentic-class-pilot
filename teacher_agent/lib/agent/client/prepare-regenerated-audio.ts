import type { Scene, ScenePatch } from '@/lib/types/stage';

/** Prepare fresh narration before committing a regenerated page to the canvas. */
export async function prepareRegeneratedAudio(
  scene: Scene,
  patch: ScenePatch,
  options: {
    enabled: boolean;
    providerId: string;
    language?: string;
    signal?: AbortSignal;
    isCurrent?: () => boolean;
    generate: (
      candidate: Scene,
      language?: string,
      signal?: AbortSignal,
    ) => Promise<{ success: boolean; failedCount: number; error?: string }>;
    dispose: (ids: readonly string[]) => Promise<void>;
  },
): Promise<ScenePatch> {
  if (!patch.actions?.some((action) => action.type === 'speech')) return patch;
  const candidate = {
    ...scene,
    ...patch,
    actions: structuredClone(patch.actions),
    timing: {
      ...scene.timing,
      measuredDurationSec: undefined,
      measurementKey: undefined,
      durationStatus: undefined,
    },
  } as Scene;
  if (!options.enabled || options.providerId === 'browser-native-tts')
    return { ...patch, timing: candidate.timing };
  const previousIds = new Set(
    patch.actions.flatMap((action) =>
      action.type === 'speech' && action.audioId ? [action.audioId] : [],
    ),
  );
  try {
    options.signal?.throwIfAborted();
    const result = await options.generate(candidate, options.language, options.signal);
    options.signal?.throwIfAborted();
    if (options.isCurrent && !options.isCurrent())
      throw new Error('配音期间本页发生了变化，请重新提交修改建议。');
    const missing = (candidate.actions ?? []).some(
      (action) =>
        action.type === 'speech' &&
        action.text.trim() &&
        (!action.audioId || action.audioInvalidated),
    );
    if (!result.success || result.failedCount || missing)
      throw new Error(
        `本页配音生成失败，请检查语音设置后重试。${result.error ? ` ${result.error}` : ''}`,
      );
    return { ...patch, actions: candidate.actions, timing: candidate.timing };
  } catch (error) {
    await options.dispose(
      (candidate.actions ?? []).flatMap((action) =>
        action.type === 'speech' && action.audioId && !previousIds.has(action.audioId)
          ? [action.audioId]
          : [],
      ),
    );
    throw error;
  }
}
