'use client';

import { EmbeddedSettingsSync } from '@/components/course-space/workspace-settings';

import { Stage } from '@/components/stage';
import { ThemeProvider } from '@/lib/hooks/use-theme';
import { useStageStore } from '@/lib/store';
import { useSettingsStore } from '@/lib/store/settings';
import {
  claimStageSceneLoadToken,
  flushStageSave,
  isCurrentStageSceneLoadToken,
} from '@/lib/store/stage';
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
  fetchClassroomForPlayer,
  hasPendingClassroomGeneration,
  runClassroomLoad,
} from '@/lib/classroom/load-classroom';
import { isIncompleteEnhancedScene } from '@/lib/learning-skills/enhanced-courseware-quality';
import { teacherReturnUrl } from '@/lib/course-space/navigation';
import { resolveClassroomGenerationModelPolicy } from '@/lib/course-space/generation-model-policy';
import { watchBackgroundClassroomGeneration } from '@/lib/classroom/watch-background-generation';
import Link from 'next/link';
import {
  canSyncClassroomSnapshot,
  createClassroomSnapshotSyncQueue,
  ClassroomSnapshotConflictError,
} from '@/lib/classroom/classroom-server-sync';

const log = createLogger('Classroom');

export default function ClassroomDetailPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const pathname = usePathname();
  const classroomId = params?.id as string;
  const returnTo = searchParams.get('from');
  const embeddedCourseWorkspace = searchParams.get('embedded') === 'course-workspace';
  // Player-only embed (student agent iframe): hide all playback chrome so the
  // embedded viewer sees just the scene canvas. See PlaybackChromeRoot.
  const playerOnlyEmbed = searchParams.get('embedded') === 'player';
  const preferServerClassroom = pathname.startsWith('/classroom-player/');

  const { loadFromStorage } = useStageStore();
  const syncStage = useStageStore((state) => state.stage);
  const syncScenes = useStageStore((state) => state.scenes);
  const generationComplete = useStageStore((state) => state.generationComplete);
  const syncOutlines = useStageStore((state) => state.outlines);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [generationFailure, setGenerationFailure] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const generationStartedRef = useRef(false);
  const snapshotSyncRef = useRef<ReturnType<typeof createClassroomSnapshotSyncQueue> | null>(null);
  const skipServerSnapshotSyncRef = useRef(false);

  const { generateRemaining, retrySingleOutline, stop } = useSceneGenerator({
    onSceneFailed: (outline, reason) => setGenerationFailure(`${outline.title}：${reason}`),
    onComplete: () => {
      setGenerationFailure(null);
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
    async (isEffectCurrent: () => boolean = () => true, refreshServer = false) => {
      if (refreshServer) await flushStageSave();
      if (!isEffectCurrent()) return;
      const loadToken = claimStageSceneLoadToken();
      const isCurrent = () => isEffectCurrent() && isCurrentStageSceneLoadToken(loadToken);

      await runClassroomLoad({
        classroomId,
        preferServerClassroom,
        shouldRefreshFromServer: () =>
          refreshServer || hasPendingClassroomGeneration(useStageStore.getState()),
        loadToken,
        isCurrent,
        // A progress refresh must not briefly re-apply an old zero-page cache:
        // that could be echoed back to the server as a teacher edit.
        loadFromStorage: refreshServer ? async () => {} : loadFromStorage,
        getCurrentStage: () => useStageStore.getState().stage,
        fetchClassroom: async (id, shouldConvert, replaceExisting) => {
          const { stage: stageBeforeRead, scenes: scenesBeforeRead } = useStageStore.getState();
          const classroom = await (playerOnlyEmbed
            ? fetchClassroomForPlayer(id)
            : defaultClassroomLoadDeps.fetchClassroom(id, shouldConvert, {}, replaceExisting));
          if (classroom && !playerOnlyEmbed) {
            const current = useStageStore.getState();
            // Keep edits made while the server read/conversion was in flight.
            // The next serial refresh flushes them before reading again.
            if (
              refreshServer &&
              (current.stage !== stageBeforeRead || current.scenes !== scenesBeforeRead)
            )
              return null;
            const versions = (scenes: typeof current.scenes) =>
              JSON.stringify(
                scenes.map((scene) => [
                  scene.id,
                  scene.order,
                  scene.updatedAt,
                  scene.timing?.measurementKey,
                ]),
              );
            if (
              !preferServerClassroom &&
              current.stage?.id === id &&
              versions(current.scenes) === versions(classroom.scenes) &&
              JSON.stringify(current.stage.generationPlan) ===
                JSON.stringify(classroom.stage.generationPlan)
            )
              return null;
            skipServerSnapshotSyncRef.current = classroom.serverSnapshot === true;
          }
          return classroom;
        },
        applyFallbackScenes: (args) => {
          const { stage: stageBeforeHydration, scenes: scenesBeforeHydration } =
            useStageStore.getState();
          return defaultClassroomLoadDeps.applyFallbackScenes({
            ...args,
            isCurrent: () =>
              isCurrent() &&
              (!refreshServer ||
                (useStageStore.getState().stage === stageBeforeHydration &&
                  useStageStore.getState().scenes === scenesBeforeHydration)),
            applyStageAndScenes: (stage, scenes, options) =>
              applyClassroomStageAndScenes(stage, scenes, {
                ...options,
                persist: !playerOnlyEmbed,
                preserveMode: refreshServer,
              }),
          });
        },
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
    [classroomId, embeddedCourseWorkspace, loadFromStorage, playerOnlyEmbed, preferServerClassroom],
  );

  useEffect(() => {
    // Reset loading state on course switch to unmount Stage during transition,
    // preventing stale data from syncing back to the new course
    /* eslint-disable react-hooks/set-state-in-effect -- Course switch must hide stale Stage before async load */
    setLoading(true);
    setError(null);
    setGenerationFailure(null);
    /* eslint-enable react-hooks/set-state-in-effect */
    generationStartedRef.current = false;
    skipServerSnapshotSyncRef.current = false;

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

  const pendingServerJobId =
    embeddedCourseWorkspace &&
    syncStage?.id === classroomId &&
    hasPendingClassroomGeneration({
      stage: syncStage,
      scenes: syncScenes,
      outlines: syncOutlines,
      generationComplete,
    })
      ? syncStage.generationPlan?.serverJobId
      : undefined;
  useEffect(() => {
    if (loading || error || !pendingServerJobId) return;
    return watchBackgroundClassroomGeneration({
      readStatus: async () => {
        const response = await fetch(
          `/api/course-space/jobs/${encodeURIComponent(pendingServerJobId)}`,
          { cache: 'no-store' },
        );
        if (!response.ok) return undefined;
        const data = await response.json();
        return data.job?.status;
      },
      refresh: async (isCurrent) => {
        await loadClassroom(isCurrent, true);
        return !hasPendingClassroomGeneration(useStageStore.getState());
      },
    });
  }, [error, loading, pendingServerJobId, loadClassroom]);

  useEffect(() => {
    let cancelled = false;
    const queue = createClassroomSnapshotSyncQueue(undefined, (syncError) => {
      if (syncError instanceof ClassroomSnapshotConflictError) {
        stop();
        setGenerationFailure(null);
        setLoading(true);
        generationStartedRef.current = false;
        void loadClassroom(() => !cancelled, true).then(() => {
          if (!cancelled) queue.resumeAfterReload();
        });
        return;
      }
      log.error('[Classroom] Failed to sync classroom; retrying:', syncError);
    });
    snapshotSyncRef.current = queue;
    return () => {
      cancelled = true;
      queue.dispose();
      snapshotSyncRef.current = null;
    };
  }, [classroomId, loadClassroom, stop]);

  // Course-space generation enters after the first scene. Save each new scene
  // to the server as it arrives, as well as subsequent teacher edits; the
  // student player reads this server copy rather than browser IndexedDB.
  useEffect(() => {
    if (loading || error || playerOnlyEmbed) return;
    // Loading newer server pages is a read. Echoing a partial read back could
    // replace pages another window generated after that read.
    if (skipServerSnapshotSyncRef.current) {
      skipServerSnapshotSyncRef.current = false;
      return;
    }
    const snapshot = { stage: syncStage, scenes: syncScenes, generationComplete };
    if (!canSyncClassroomSnapshot(classroomId, snapshot)) return;
    snapshotSyncRef.current?.enqueue({ stage: snapshot.stage, scenes: snapshot.scenes });
  }, [classroomId, error, generationComplete, loading, playerOnlyEmbed, syncScenes, syncStage]);

  const missingGenerationPlan =
    !loading &&
    !playerOnlyEmbed &&
    syncOutlines.length === 0 &&
    hasPendingClassroomGeneration({ stage: syncStage, scenes: syncScenes, generationComplete });

  // Auto-resume generation for pending outlines
  useEffect(() => {
    if (loading || error || playerOnlyEmbed || generationStartedRef.current) return;

    const state = useStageStore.getState();
    const { outlines, scenes, stage, generationComplete } = state;
    // Server tasks own their full plan, including cancelled/failed drafts.
    // Opening a partial classroom must never start a second browser worker.
    if (stage?.generationPlan?.serverJobId) return;

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
      const modelPolicy = resolveClassroomGenerationModelPolicy({
        persistedPolicy: stage.generationModelPolicy,
        sessionPreference: params.preferServerModel,
        embeddedCourseWorkspace,
        returnTo,
      });
      if (stage.generationModelPolicy !== modelPolicy)
        useStageStore.getState().updateStage({ generationModelPolicy: modelPolicy });

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
          preferServerModel: modelPolicy === 'server',
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
  }, [loading, error, generateRemaining, playerOnlyEmbed, embeddedCourseWorkspace, returnTo]);

  return (
    <ThemeProvider>
      <MediaStageProvider value={classroomId}>
        <div className="h-screen flex flex-col overflow-hidden">
          {!playerOnlyEmbed && !embeddedCourseWorkspace && (
            <nav
              aria-label="课件导航"
              className="flex shrink-0 items-center justify-between border-b bg-white px-4 py-2 text-sm text-slate-700"
            >
              <Link href={teacherReturnUrl(searchParams.get('from'))} className="hover:underline">
                ← 返回课程
              </Link>
              <Link href="/course-space" className="hover:underline">
                课程中心
              </Link>
            </nav>
          )}
          {generationFailure && !playerOnlyEmbed && (
            <div
              role="alert"
              className="shrink-0 border-b border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
            >
              {generationFailure}
            </div>
          )}
          {missingGenerationPlan && (
            <div
              role="status"
              className="flex shrink-0 items-center justify-between gap-3 border-b bg-amber-50 px-4 py-2 text-sm text-amber-900"
            >
              <span>课件尚未完整载入，当前显示 {syncScenes.length} 页。</span>
              <button
                disabled={refreshing}
                className="shrink-0 underline disabled:opacity-50"
                onClick={async () => {
                  setRefreshing(true);
                  try {
                    await loadClassroom();
                  } finally {
                    setRefreshing(false);
                  }
                }}
              >
                {refreshing ? '正在刷新…' : '刷新生成进度'}
              </button>
            </div>
          )}
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
            <>
              {embeddedCourseWorkspace && <EmbeddedSettingsSync />}
              <Stage
                onRetryOutline={async (outlineId) => {
                  setGenerationFailure(null);
                  await retrySingleOutline(outlineId);
                }}
                forceEditMode={embeddedCourseWorkspace}
                videoOnly={playerOnlyEmbed}
                hidePlaybackTiming={searchParams.get('replay') === '1'}
              />
            </>
          )}
        </div>
      </MediaStageProvider>
    </ThemeProvider>
  );
}
