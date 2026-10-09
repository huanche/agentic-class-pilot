import type { Scene } from '@/lib/types/stage';

type PlaylistScene = Pick<Scene, 'id' | 'type'>;

/** Return the next lecture slide after `currentSceneId`, skipping activities. */
export function nextStudentPlaybackSlide(
  scenes: readonly PlaylistScene[],
  currentSceneId: string | null | undefined,
): PlaylistScene | undefined {
  if (!currentSceneId) return undefined;
  const currentIndex = scenes.findIndex((scene) => scene.id === currentSceneId);
  if (currentIndex < 0) return undefined;
  return scenes.slice(currentIndex + 1).find((scene) => scene.type === 'slide');
}

/** The student video phase ends after the final slide, not the final activity. */
export function isFinalStudentPlaybackSlide(
  scenes: readonly PlaylistScene[],
  currentSceneId: string,
): boolean {
  const currentIndex = scenes.findIndex((scene) => scene.id === currentSceneId);
  return (
    currentIndex >= 0 && !scenes.slice(currentIndex + 1).some((scene) => scene.type === 'slide')
  );
}
