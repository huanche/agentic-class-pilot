import type { Scene } from '@/lib/types/stage';

type PlaylistScene = Pick<Scene, 'id' | 'type'>;

/** Return the next scene in the complete student lesson. */
export function nextStudentPlaybackSlide(
  scenes: readonly PlaylistScene[],
  currentSceneId: string | null | undefined,
): PlaylistScene | undefined {
  if (!currentSceneId) return undefined;
  const currentIndex = scenes.findIndex((scene) => scene.id === currentSceneId);
  if (currentIndex < 0) return undefined;
  return scenes[currentIndex + 1];
}

/** The student lesson ends after its final scene. */
export function isFinalStudentPlaybackSlide(
  scenes: readonly PlaylistScene[],
  currentSceneId: string,
): boolean {
  const currentIndex = scenes.findIndex((scene) => scene.id === currentSceneId);
  return currentIndex >= 0 && currentIndex === scenes.length - 1;
}
