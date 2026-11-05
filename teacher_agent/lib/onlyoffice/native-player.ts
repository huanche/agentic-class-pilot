import type { Scene, Stage } from '@/lib/types/stage';

export interface NativePptxDriver {
  ready: Promise<void>;
  seek(step: number): Promise<void>;
  pause(): void;
  resume(): void;
  reset(): void;
}
const drivers = new Map<string, NativePptxDriver>();
export function nativePptxPage(stage: Stage | null | undefined, scene: Scene | undefined | null) {
  return scene?.type === 'slide' && !scene.nativePptxEdited && scene.outlineId
    ? stage?.nativePptx?.pages[scene.outlineId]
    : undefined;
}
export function nativeDriver(sceneId: string) {
  return drivers.get(sceneId);
}
export function registerNativeDriver(sceneId: string, driver: NativePptxDriver) {
  drivers.set(sceneId, driver);
  return () => {
    if (drivers.get(sceneId) === driver) drivers.delete(sceneId);
  };
}
export async function waitNativeDriver(sceneId: string): Promise<NativePptxDriver> {
  const started = Date.now();
  while (!drivers.has(sceneId)) {
    if (Date.now() - started > 30000) throw new Error('原稿播放器连接超时，请重新加载');
    await new Promise((resolve) => setTimeout(resolve, 40));
  }
  const driver = drivers.get(sceneId)!;
  await driver.ready;
  return driver;
}
