'use client';

import { Stage } from '@/components/stage';
import { ThemeProvider } from '@/lib/hooks/use-theme';
import { useStageStore } from '@/lib/store';
import { useSettingsStore } from '@/lib/store/settings';
import { claimStageSceneLoadToken, isCurrentStageSceneLoadToken } from '@/lib/store/stage';
import { loadImageMapping } from '@/lib/utils/image-storage';
import { useEffect, useRef, useState, useCallback } from 'react';
import { useParams, usePathname, useSearchParams } from 'next/navigation';
import { useSceneGenerator } from '@/lib/hooks/use-scene-generator';
import { useMediaGenerationStore } from '@/lib/store/media-generation';
import { useWhiteboardHistoryStore } from '@/lib/store/whiteboard-history';
import { createLogger } from '@/lib/logger';
import { MediaStageProvider } from '@/lib/contexts/media-stage-context';
import { generateMediaForOutlines } from '@/lib/media/media-orchestrator';
import { loadImportedPptSlides, removeImportedPptSlides } from '@/lib/import/pptx-course';
import { useAgentRegistry } from '@/lib/orchestration/registry/store';
import {
  applyClassroomStageAndScenes,
  defaultClassroomLoadDeps,
  runClassroomLoad,
} from '@/lib/classroom/load-classroom';
import { isIncompleteEnhancedScene } from '@/lib/learning-skills/enhanced-courseware-quality';

const log = createLogger('Classroom');

export default function ClassroomDetailPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const pathname = usePathname();
  const classroomId = params?.id as string;
  const embeddedCourseWorkspace = searchParams.get('embedded') === 'course-workspace';
  // Player-only embed (student agent iframe): hide all playback chrome so the
  // embedded viewer sees just the scene canvas. See PlaybackChromeRoot.
  const playerOnlyEmbed = searchParams.get('embedded') === 'player';
  const preferServerClassroom = pathname.startsWith('/classroom-player/');

  const { loadFromStorage } = useStageStore();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const generationStartedRef = useRef(false);

  const { generateRemaining, retrySingleOutline, stop } = useSceneGenerator({
    onComplete: () => {
      log.info('[Classroom] All scenes generated');
      const raw = sessionStorage.getItem('generationParams');
      let importKey: string | undefined;
      try {
        importKey = raw
          ? (JSON.parse(raw) as { pptxImportStorageKey?: string }).pptxImportStorageKey
          : undefined;
      } catch {
        // A malformed transient record should not prevent completion cleanup.
      }
      void removeImportedPptSlides(importKey);
      sessionStorage.removeItem('generationParams');
    },
  });

  const loadClassroom = useCallback(
    async (isEffectCurrent: () => boolean = () => true) => {
      const loadToken = claimStageSceneLoadToken();
      const isCurrent = () => isEffectCurrent() && isCurrentStageSceneLoadToken(loadToken);

      await runClassroomLoad({
        classroomId,
        preferServerClassroom,
        loadToken,
        isCurrent,
        loadFromStorage,
        getCurrentStage: () => useStageStore.getState().stage,
        fetchClassroom: (id, shouldConvert, replaceExisting) =>
          defaultClassroomLoadDeps.fetchClassroom(id, shouldConvert, {}, replaceExisting),
        applyFallbackScenes: (args) =>
          defaultClassroomLoadDeps.applyFallbackScenes({
            ...args,
            isCurrent,
            applyStageAndScenes: applyClassroomStageAndScenes,
          }),
        loadRestoredMediaTasks: defaultClassroomLoadDeps.loadRestoredMediaTasks,
        applyRestoredMediaTasks: defaultClassroomLoadDeps.applyRestoredMediaTasks,
        discardRestoredMediaTasks: defaultClassroomLoadDeps.discardRestoredMediaTasks,
        loadLegacyAgentFallbacks: defaultClassroomLoadDeps.loadLegacyAgentFallbacks,
        commitMigratedAgentConfigs: defaultClassroomLoadDeps.commitMigratedAgentConfigs,
        applyGeneratedAgents: defaultClassroomLoadDeps.applyGeneratedAgents,
        getSettings: () => useSettingsStore.getState(),
        getAgent: (id) => useAgentRegistry.getState().getAgent(id),
        restoreAgentSelection: defaultClassroomLoadDeps.restoreAgentSelection,
        setError,
        setLoading,
        log,
      });
    },
    [classroomId, embeddedCourseWorkspace, loadFromStorage, preferServerClassroom],
  );

  useEffect(() => {
    // Reset loading state on course switch to unmount Stage during transition,
    // preventing stale data from syncing back to the new course
    /* eslint-disable react-hooks/set-state-in-effect -- Course switch must hide stale Stage before async load */
    setLoading(true);
    setError(null);
    /* eslint-enable react-hooks/set-state-in-effect */
    generationStartedRef.current = false;

    // Clear previous classroom's media tasks to prevent cross-classroom contamination.
    // Placeholder IDs (gen_img_1, gen_vid_1) are NOT globally unique across stages,
    // so stale tasks from a previous classroom would shadow the new one's.
    const mediaStore = useMediaGenerationStore.getState();
    mediaStore.revokeObjectUrls();
    useMediaGenerationStore.setState({ tasks: {} });

    // Clear whiteboard history to prevent snapshots from a previous course leaking in.
    useWhiteboardHistoryStore.getState().clearHistory();

    let cancelled = false;
    loadClassroom(() => !cancelled);

    // Cancel ongoing generation when classroomId changes or component unmounts
    return () => {
      cancelled = true;
      stop();
    };
  }, [classroomId, loadClassroom, stop]);

  // Auto-resume generation for pending outlines
  useEffect(() => {
    if (loading || error || generationStartedRef.current) return;

    const state = useStageStore.getState();
    const { outlines, scenes, stage, generationComplete } = state;

    // Repair AI-enhanced pages that contain a generation plan rather than
    // student-facing teaching content. This also recovers old saved courses;
    // the regenerated scenes receive fresh narration and aligned focus cues.
    const incompleteOrders = new Set(
      outlines.flatMap((outline) => {
        const scene = scenes.find((candidate) => candidate.order === outline.order);
        return scene && isIncompleteEnhancedScene(outline, scene) ? [outline.order] : [];
      }),
    );
    if (incompleteOrders.size > 0 && stage) {
      generationStartedRef.current = true;
      useStageStore.setState({
        scenes: scenes.filter((scene) => !incompleteOrders.has(scene.order)),
        generationComplete: false,
      });
      generateRemaining({
        stageInfo: {
          name: stage.name || '',
          description: stage.description,
          style: stage.style,
        },
        languageDirective: stage.languageDirective,
        preferServerModel: true,
      });
      return;
    }

    // Check if there are pending outlines. A finished deck is frozen for
    // editing: deleting a slide leaves its outline orphaned, but that must not
    // be treated as an interrupted generation and regenerated. Only resume
    // when generation has not completed.
    const completedOrders = new Set(scenes.map((s) => s.order));
    const hasPending = !generationComplete && outlines.some((o) => !completedOrders.has(o.order));

    if (hasPending && stage) {
      generationStartedRef.current = true;

      // Load generation params from sessionStorage (stored by generation-preview before navigating)
      const genParamsStr = sessionStorage.getItem('generationParams');
      const params = genParamsStr ? JSON.parse(genParamsStr) : {};

      // Reconstruct imageMapping from IndexedDB using pdfImages storageIds
      const storageIds = (params.pdfImages || [])
        .map((img: { storageId?: string }) => img.storageId)
        .filter(Boolean);

      Promise.all([
        loadImageMapping(storageIds),
        loadImportedPptSlides(params.pptxImportStorageKey),
      ]).then(([imageMapping, importedSlides]) => {
        const reviewedOriginalIndices = Array.isArray(params.pptxIncludedOriginalIndices)
          ? (params.pptxIncludedOriginalIndices as number[])
          : undefined;
        const reviewedSlides = reviewedOriginalIndices
          ? reviewedOriginalIndices
              .map((originalIndex) => importedSlides?.[originalIndex])
              .filter((slide): slide is NonNullable<typeof slide> => Boolean(slide))
          : importedSlides;
        generateRemaining({
          pdfImages: params.pdfImages,
          imageMapping,
          stageInfo: {
            name: stage.name || '',
            description: stage.description,
            style: stage.style,
          },
          agents: params.agents,
          userProfile: params.userProfile,
          languageDirective: params.languageDirective || stage.languageDirective,
          importedSlides: reviewedSlides || undefined,
          preferImportedCanvas: params.preferImportedCanvas === true,
          formulaEnhancedOrders: Array.isArray(params.formulaEnhancedOrders)
            ? params.formulaEnhancedOrders
            : undefined,
          preferServerModel: params.preferServerModel === true,
          narrationScripts: params.narrationScripts,
        });
      });
    } else if (outlines.length > 0 && stage) {
      // All scenes are generated, but some media may not have finished.
      // Resume media generation for any tasks not yet in IndexedDB.
      // generateMediaForOutlines skips already-completed tasks automatically.
      generationStartedRef.current = true;
      // The deck reached the classroom already fully materialized (e.g. a
      // single-slide course, or a deck whose last slide finished in
      // generation-preview), so generateRemaining's completion path never
      // ran. Record completion now so a later edit/delete is not treated as
      // an interrupted generation. No-op if already complete or not all
      // outlines have scenes.
      useStageStore.getState().markGenerationCompleteIfDone();
      // Resume media only for outlines that still have a scene. On a finished
      // deck the user may have deleted a slide, leaving an orphaned outline;
      // generating its media would waste API calls on a slide that is gone.
      const materializedOrders = new Set(scenes.map((s) => s.order));
      const materializedOutlines = outlines.filter((o) => materializedOrders.has(o.order));
      generateMediaForOutlines(materializedOutlines, stage.id).catch((err) => {
        log.warn('[Classroom] Media generation resume error:', err);
      });
    }
  }, [loading, error, generateRemaining]);

  return (
    <ThemeProvider>
      <MediaStageProvider value={classroomId}>
        <div className="h-screen flex flex-col overflow-hidden">
          {loading ? (
            <div className="flex-1 flex items-center justify-center bg-gray-50 dark:bg-gray-900">
              <div className="text-center text-muted-foreground">
                <p>Loading classroom...</p>
              </div>
            </div>
          ) : error ? (
            <div className="flex-1 flex items-center justify-center bg-gray-50 dark:bg-gray-900">
              <div className="text-center">
                <p className="text-destructive mb-4">Error: {error}</p>
                <button
                  onClick={() => {
                    setError(null);
                    setLoading(true);
                    loadClassroom();
                  }}
                  className="px-4 py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90"
                >
                  Retry
                </button>
              </div>
            </div>
          ) : (
            <Stage
              onRetryOutline={retrySingleOutline}
              forceEditMode={embeddedCourseWorkspace}
              videoOnly={playerOnlyEmbed}
            />
          )}
        </div>
      </MediaStageProvider>
    </ThemeProvider>
  );
}
