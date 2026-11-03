'use client';

import { useMemo } from 'react';
import { useStageStore } from '@/lib/store/stage';
import { nativePptxPage } from '@/lib/onlyoffice/native-player';
import { NativePptxView } from './native-pptx-view';
import type { Scene, StageMode } from '@/lib/types/stage';
import { SlideEditor as SlideRenderer } from '../slide-renderer/Editor';
import { QuizView } from '../scene-renderers/quiz-view';
import { InteractiveRenderer } from '../scene-renderers/interactive-renderer';
import { PBLRenderer } from '../scene-renderers/pbl-renderer';

interface SceneRendererProps {
  readonly scene: Scene;
  readonly mode: StageMode;
  readonly studentPlayer?: boolean;
  readonly onSceneComplete?: () => void;
  readonly nativeLoadTimeoutMs?: number;
}

/**
 * Playback scene dispatcher. In Pro (edit) mode, Stage renders EditShell
 * directly as a top-level takeover — SceneRenderer is only on the playback
 * path, so it does not branch on `mode === 'edit'`.
 */
export function SceneRenderer({
  scene,
  mode,
  studentPlayer,
  onSceneComplete,
  nativeLoadTimeoutMs,
}: SceneRendererProps) {
  const stage = useStageStore((s) => s.stage);
  const renderer = useMemo(() => {
    switch (scene.type) {
      case 'slide':
        if (scene.content.type !== 'slide') return <div>Invalid slide content</div>;
        if (nativePptxPage(stage, scene))
          return (
            <NativePptxView key={scene.id} scene={scene} loadTimeoutMs={nativeLoadTimeoutMs} />
          );
        return <SlideRenderer mode={mode} />;
      case 'quiz':
        if (scene.content.type !== 'quiz') return <div>Invalid quiz content</div>;
        return (
          <QuizView
            key={scene.id}
            questions={scene.content.questions}
            sceneId={scene.id}
            stageId={scene.stageId}
            studentPlayer={studentPlayer}
            onContinue={onSceneComplete}
          />
        );
      case 'interactive':
        if (scene.content.type !== 'interactive') return <div>Invalid interactive content</div>;
        return <InteractiveRenderer content={scene.content} sceneId={scene.id} />;
      case 'pbl':
        if (scene.content.type !== 'pbl') return <div>Invalid PBL content</div>;
        return <PBLRenderer content={scene.content} mode={mode} sceneId={scene.id} />;
      default:
        return <div>Unknown scene type</div>;
    }
  }, [scene, mode, studentPlayer, stage, onSceneComplete, nativeLoadTimeoutMs]);

  return <div className="w-full h-full">{renderer}</div>;
}
