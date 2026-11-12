'use client';
import { useEffect, useState } from 'react';
import { useStageStore } from '@/lib/store/stage';
import { SceneProvider } from '@/lib/contexts/scene-context';
import { SceneRenderer } from '@/components/stage/scene-renderer';
import { ActionEngine } from '@/lib/action/engine';
import { nativePptxPage } from '@/lib/onlyoffice/native-player';
import { useCanvasStore } from '@/lib/store/canvas';
import { WhiteboardCanvas } from '@/components/whiteboard/whiteboard-canvas';
import type { ClassroomVideoPlan } from '@/lib/classroom-video/types';
import {
  createCaptureReadinessGate,
  CAPTURE_SOURCE_LOAD_TIMEOUT_MS,
} from '@/lib/classroom-video/capture-readiness';

export interface CaptureResult {
  endEpoch: number;
  speech: { actionId: string; epoch: number }[];
}
declare global {
  interface Window {
    classroomCapture?: {
      ready(sceneId: string): Promise<void>;
      run(durations: Record<string, number>): Promise<CaptureResult>;
    };
    classroomCaptureError?: string;
  }
}
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
const frame = () => new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));

/** Private render surface. It has no editor, autosave, generation, or live audio. */
export function ClassroomCaptureSurface({ id, version }: { id: string; version: string }) {
  const [plan, setPlan] = useState<ClassroomVideoPlan>();
  const scene = useStageStore((s) => s.scenes.find((v) => v.id === s.currentSceneId));
  const whiteboard = useStageStore((s) => s.stage?.whiteboard?.[0]);
  const boardOpen = useCanvasStore((s) => s.whiteboardOpen);
  useEffect(() => {
    let disposed = false;
    const engine = new ActionEngine(useStageStore);
    const readiness = createCaptureReadinessGate();
    delete window.classroomCaptureError;
    void fetch(`/api/classroom?id=${encodeURIComponent(id)}&videoCapture=${version}`, {
      cache: 'no-store',
    })
      .then(async (r) => {
        const body = await r.json();
        if (!r.ok || !body.plan) throw new Error(body.error || 'Video snapshot unavailable');
        return body.plan as ClassroomVideoPlan;
      })
      .then((snapshot) => {
        if (disposed) return;
        useStageStore.setState({
          stage: snapshot.stage,
          scenes: snapshot.scenes,
          mode: 'playback',
          currentSceneId: null,
          generationComplete: true,
        });
        setPlan(snapshot);
        window.classroomCapture = {
          async ready(sceneId) {
            await readiness.prepare(sceneId, async () => {
              const target = snapshot.scenes.find((s) => s.id === sceneId);
              if (!target || target.type !== 'slide') throw new Error('Invalid capture scene');
              useStageStore.setState({ currentSceneId: sceneId });
              await frame();
              await frame();
              // Set reveal visibility before the first captured frame.
              const targets = (target.actions || []).flatMap((a) =>
                a.type === 'reveal' && !a.pptxStep ? [a.elementId] : [],
              );
              engine.clearEffects();
              useCanvasStore.getState().setHiddenElementIdList(targets);
              useCanvasStore.getState().setRevealedElementIdList([]);
              useCanvasStore.getState().setWhiteboardOpen(false);
              await engine.ensureSourceReady(sceneId);
              await document.fonts.ready;
              await Promise.all(
                Array.from(document.images).map((image) =>
                  image.decode().catch(() => {
                    if (!image.naturalWidth) throw new Error('页面图片未加载完成');
                  }),
                ),
              );
              await frame();
              await frame();
            });
          },
          async run(durations) {
            const state = useStageStore.getState();
            const target = state.scenes.find((s) => s.id === state.currentSceneId);
            if (!target) throw new Error('课件页面尚未加载');
            readiness.assertReady(target.id);
            const speech: CaptureResult['speech'] = [];
            for (const action of target.actions || []) {
              if (action.type === 'speech') {
                const duration = durations[action.id];
                if (!(duration > 0)) throw new Error(`配音时长无效: ${action.id}`);
                speech.push({
                  actionId: action.id,
                  epoch: performance.timeOrigin + performance.now(),
                });
                await sleep(duration * 1000);
              } else {
                // Unsupported live actions must never silently disappear from a video.
                if (
                  !['reveal', 'spotlight', 'laser'].includes(action.type) &&
                  !action.type.startsWith('wb_')
                )
                  throw new Error(`此页包含尚不支持转视频的动作: ${action.type}`);
                await engine.execute(action, { persistEffects: true });
              }
            }
            await sleep(300);
            engine.clearEffects();
            return { speech, endEpoch: performance.timeOrigin + performance.now() };
          },
        };
      })
      .catch((e) => {
        window.classroomCaptureError = e.message;
      });
    return () => {
      disposed = true;
      readiness.invalidate();
      delete window.classroomCapture;
      engine.clearEffects();
    };
  }, [id, version]);
  return (
    <div data-video-capture className="fixed inset-0 overflow-hidden bg-white">
      <style>{`[data-video-capture] [data-native-pptx] > .absolute.right-2 {display:none!important} html,body{margin:0!important;overflow:hidden!important}`}</style>
      {plan && scene && (
        <SceneProvider>
          <SceneRenderer
            scene={scene}
            mode="playback"
            nativeLoadTimeoutMs={CAPTURE_SOURCE_LOAD_TIMEOUT_MS}
          />
        </SceneProvider>
      )}
      {boardOpen && whiteboard && (
        <div className="absolute inset-0 bg-white">
          <WhiteboardCanvas whiteboard={whiteboard} />
        </div>
      )}
      {scene && !nativePptxPage(plan?.stage, scene) && (
        <span className="sr-only">Web canvas capture</span>
      )}
    </div>
  );
}
