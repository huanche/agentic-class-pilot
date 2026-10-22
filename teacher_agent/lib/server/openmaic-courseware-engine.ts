/** OpenMAIC ordering: first ready scene, bounded content ahead, ordered actions + narration.
 * Models and persistence are ports so retries/cancellation can be verified without paid calls.
 */
import type { Scene } from '@/lib/types/stage';
import type { SceneOutline } from '@/lib/types/generation';
import { createCoursewarePrefetch } from './courseware-prefetch';

export interface OpenmaicCheckpoint<T> {
  content?: T;
  scene?: Scene;
}
export interface OpenmaicEngineServices<T> {
  content(outline: SceneOutline, signal: AbortSignal): Promise<T>;
  actions(
    outline: SceneOutline,
    content: T,
    previous: Scene | undefined,
    signal: AbortSignal,
  ): Promise<Scene>;
  narrate(scene: Scene, signal: AbortSignal): Promise<void>;
  read(order: number): Promise<OpenmaicCheckpoint<T>>;
  checkpoint(order: number, value: OpenmaicCheckpoint<T>): Promise<void>;
  save(scene: Scene): Promise<void>;
  discard(scene: Scene): Promise<void>;
  phase(name: 'content' | 'actions' | 'audio', outline: SceneOutline): Promise<void>;
}

export async function generateOpenmaicCourseware<T>(options: {
  outlines: SceneOutline[];
  completed: Scene[];
  concurrency: number;
  signal: AbortSignal;
  services: OpenmaicEngineServices<T>;
}) {
  const { signal, services } = options;
  const completed = [...options.completed].sort((a, b) => a.order - b.order);
  const missing = [...options.outlines]
    .sort((a, b) => a.order - b.order)
    .filter((outline) => !completed.some((scene) => scene.order === outline.order));
  const prepare = async (
    outline: SceneOutline,
    callSignal: AbortSignal,
  ): Promise<OpenmaicCheckpoint<T>> => {
    const checkpoint = await services.read(outline.order);
    if (checkpoint.content !== undefined || checkpoint.scene) return checkpoint;
    const value = { content: await services.content(outline, callSignal) };
    callSignal.throwIfAborted();
    await services.checkpoint(outline.order, value);
    return value;
  };
  let ahead: ReturnType<typeof createCoursewarePrefetch<OpenmaicCheckpoint<T>>> | undefined;
  try {
    for (let index = 0; index < missing.length; index++) {
      signal.throwIfAborted();
      const outline = missing[index];
      await services.phase('content', outline);
      // Give the first page the model quota before warming the remaining pages.
      const checkpoint =
        index === 0 ? await prepare(outline, signal) : await ahead!.take(index - 1);
      const previous = completed.filter((scene) => scene.order < outline.order).at(-1);
      await services.phase('actions', outline);
      const scene = checkpoint.scene
        ? structuredClone(checkpoint.scene)
        : await services.actions(outline, checkpoint.content!, previous, signal);
      if (!checkpoint.scene) {
        signal.throwIfAborted();
        await services.checkpoint(outline.order, { ...checkpoint, scene });
      }
      let saved = false;
      try {
        await services.phase('audio', outline);
        await services.narrate(scene, signal);
        signal.throwIfAborted();
        await services.save(scene);
        saved = true;
        completed.push(scene);
        completed.sort((a, b) => a.order - b.order);
      } finally {
        if (!saved) await services.discard(scene);
      }
      if (index === 0 && missing.length > 1) {
        ahead = createCoursewarePrefetch(
          missing.length - 1,
          options.concurrency,
          (next, callSignal) => prepare(missing[next + 1], callSignal),
          signal,
        );
      }
    }
    return completed;
  } finally {
    await ahead?.close();
  }
}
