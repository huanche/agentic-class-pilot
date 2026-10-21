import fs from 'node:fs/promises';
import path from 'node:path';
import { withGenerationRetry } from '@openmaic/generation';
import type { BackgroundCoursewareInput } from '@/lib/generation/background-courseware';
import { isActiveCourseJob } from '@/lib/generation/background-courseware';
import type { CourseArtifactJob } from '@/lib/course-space/types';
import type { Scene } from '@/lib/types/stage';
import {
  getOutlineDurationSeconds,
  QUIZ_SECONDS_PER_QUESTION,
} from '@/lib/playback/timing-display';
import {
  CLASSROOM_JOBS_DIR,
  persistClassroom,
  readClassroom,
  writeJsonFileAtomic,
} from './classroom-storage';
import { readCourseJob, mutateCourseJob, saveCourseArtifact } from './course-space-storage';
import { fetchPlatformUserModelConfig } from './platform-user-model-config';
import { createCoursewarePerformance } from './courseware-performance';
import { createOpenmaicCoursewareSteps, type OpenmaicContent } from './openmaic-courseware-steps';
import { generateOpenmaicCourseware, type OpenmaicCheckpoint } from './openmaic-courseware-engine';
import { getParallelTtsConcurrency } from './provider-config';
import {
  generateTTSForClassroom,
  finalizeClassroomTtsAudio,
  removeClassroomTtsAudio,
  generateMediaForClassroom,
  replaceMediaPlaceholders,
} from './classroom-media-generation';

export async function executeOpenmaicCourseware(
  jobId: string,
  stored: { input: BackgroundCoursewareInput; teacherId: string; baseUrl: string },
  controller: AbortController,
  requestHeaders: Record<string, string>,
  acquireSlot: (signal: AbortSignal) => Promise<() => void>,
) {
  const { input, teacherId, baseUrl } = stored;
  const { stage, outlines } = input;
  const signal = controller.signal;
  const concurrency = Math.max(
    1,
    Math.min(4, Number(process.env.COURSEWARE_CONTENT_PREFETCH) || 2),
  );
  const metrics = createCoursewarePerformance(true, concurrency);
  const performanceSnapshot = (finished = false) => ({
    ...metrics.snapshot(finished),
    engine: 'openmaic' as const,
  });
  let release: (() => void) | undefined;
  let heartbeat: ReturnType<typeof setInterval> | undefined;
  let scenes: Scene[] = [];
  const check = async () => {
    signal.throwIfAborted();
    const job = await readCourseJob(jobId);
    if (!job || !isActiveCourseJob(job.status)) {
      controller.abort();
      signal.throwIfAborted();
    }
    return job!;
  };
  const snapshot = () => {
    stage.updatedAt = Date.now();
    return metrics.measure('save', () =>
      persistClassroom({ id: stage.id, stage, scenes }, baseUrl),
    );
  };
  const progress = (job: CourseArtifactJob, phase: string) => ({
    ...job.backgroundGeneration!,
    classroomId: stage.id,
    completedPages: scenes.length,
    totalPages: outlines.length,
    phase,
    performance: performanceSnapshot(),
  });
  const checkpointPath = (order: number) =>
    path.join(CLASSROOM_JOBS_DIR, `${jobId}.openmaic-page-${order}.json`);
  try {
    await check();
    heartbeat = setInterval(() => {
      void check()
        .then(() =>
          mutateCourseJob(jobId, (job) =>
            isActiveCourseJob(job.status) && job.backgroundGeneration
              ? {
                  ...job,
                  backgroundGeneration: {
                    ...job.backgroundGeneration,
                    performance: performanceSnapshot(),
                  },
                }
              : job,
          ),
        )
        .catch(() => controller.abort());
    }, 2000);
    release = await metrics.measure('queue', () => acquireSlot(signal));
    const saved = await readClassroom(stage.id);
    scenes = saved?.scenes ?? [];
    stage.generationModelPolicy = 'server';
    stage.timing = { ...stage.timing, durationPolicy: 'target' };
    stage.generationPlan = { version: 1, outlines, complete: false, serverJobId: jobId };
    await snapshot();
    const config =
      process.env.PLATFORM_AUTH_ENABLED === 'true'
        ? await fetchPlatformUserModelConfig(teacherId)
        : undefined;
    const steps = createOpenmaicCoursewareSteps(input, config, requestHeaders);
    const retry = <T>(
      phase: string,
      order: number,
      work: (callSignal: AbortSignal) => Promise<T>,
      callSignal: AbortSignal,
    ) =>
      withGenerationRetry(() => metrics.measure(phase, () => work(callSignal), order), {
        maxRetries: 2,
        label: `${jobId} ${phase} ${order}`,
        signal: callSignal,
      });
    await generateOpenmaicCourseware({
      outlines,
      completed: scenes,
      concurrency,
      signal,
      services: {
        content: (outline, callSignal) =>
          retry('content', outline.order, (s) => steps.content(outline, s), callSignal),
        actions: (outline, content, previous, callSignal) =>
          retry(
            'actions',
            outline.order,
            (s) => steps.actions(outline, content, previous, s),
            callSignal,
          ),
        read: async (order) => {
          try {
            return JSON.parse(
              await fs.readFile(checkpointPath(order), 'utf8'),
            ) as OpenmaicCheckpoint<OpenmaicContent>;
          } catch (error) {
            if ((error as NodeJS.ErrnoException).code === 'ENOENT') return {};
            throw error;
          }
        },
        checkpoint: async (order, checkpoint) => {
          await check();
          await writeJsonFileAtomic(checkpointPath(order), checkpoint);
        },
        phase: async (phase, outline) => {
          await check();
          await mutateCourseJob(jobId, (job) =>
            isActiveCourseJob(job.status)
              ? {
                  ...job,
                  status: 'running',
                  progress: Math.round((scenes.length / outlines.length) * 95),
                  message: `第 ${outline.order}/${outlines.length} 页：${{ content: '生成画面', actions: '生成讲稿与动作', audio: '生成配音' }[phase]}`,
                  backgroundGeneration: progress(job, phase),
                }
              : job,
          );
        },
        narrate: async (scene) => {
          const outline = outlines.find((page) => page.order === scene.order)!;
          scene.timing = {
            plannedDurationSec: getOutlineDurationSeconds(
              outline,
              stage.timing?.targetDurationMinutes ?? 28,
              outlines.length,
            ),
            mode:
              scene.type === 'quiz'
                ? 'quiz'
                : scene.type === 'interactive'
                  ? 'interactive-demo'
                  : 'narration-fit',
            quizSecondsPerQuestion: scene.type === 'quiz' ? QUIZ_SECONDS_PER_QUESTION : undefined,
            autoAdvance: true,
          };
          if (!input.enableTTS || !scene.actions?.some((action) => action.type === 'speech'))
            return;
          await metrics.measure(
            'audio',
            async () => {
              const result = await generateTTSForClassroom(
                [scene],
                stage.id,
                baseUrl,
                config?.tts,
                {
                  concurrency: getParallelTtsConcurrency(),
                  signal,
                  failFast: true,
                  isolateAudio: true,
                  recordUsage: true,
                  cacheScope: teacherId,
                  voiceSelection: input.ttsVoice,
                  languageDirective: stage.languageDirective,
                  onAudioCache: (status) => metrics.cache(status),
                },
              );
              if (result.failed || !result.generated)
                throw new Error('配音未完成，请检查语音服务配置后重试');
            },
            scene.order,
          );
        },
        save: async (scene) => {
          await check();
          // Cancellation and a completed page commit share the job lock. Never erase committed audio.
          let committed = false;
          await mutateCourseJob(jobId, async (job) => {
            if (!isActiveCourseJob(job.status)) return job;
            await finalizeClassroomTtsAudio(scene, stage.id, baseUrl);
            scenes.push(scene);
            scenes.sort((a, b) => a.order - b.order);
            await snapshot();
            const artifactId = `artifact_${jobId}`;
            await saveCourseArtifact({
              id: artifactId,
              jobId,
              teacherId: job.teacherId,
              courseId: job.courseId,
              scope: job.scope,
              type: 'lesson-courseware',
              title: stage.name,
              status: 'review',
              citations: [],
              content: `课件正在生成，已完成 ${scenes.length}/${outlines.length} 页。`,
              classroomId: stage.id,
              classroomUrl: `/classroom/${stage.id}`,
              createdAt: job.createdAt,
              updatedAt: Date.now(),
            });
            metrics.pageReady();
            committed = true;
            return {
              ...job,
              artifactId,
              progress: Math.round((scenes.length / outlines.length) * 95),
              message: `已完成 ${scenes.length}/${outlines.length} 页，可先查看已完成页面`,
              backgroundGeneration: progress(job, 'page-complete'),
            };
          });
          if (!committed) {
            controller.abort();
            signal.throwIfAborted();
          }
        },
        discard: async (scene) => {
          // A snapshot may have committed even if writing its artifact failed.
          const saved = await readClassroom(stage.id);
          if (!saved?.scenes.some((page) => page.id === scene.id))
            await removeClassroomTtsAudio(scene, stage.id);
        },
      },
    });
    await check();
    if (input.enableMedia && outlines.some((outline) => outline.mediaGenerations?.length)) {
      const mediaOutlines = outlines.map((outline) => ({
        ...outline,
        mediaGenerations: outline.mediaGenerations?.filter((request) =>
          request.type === 'image'
            ? (input.enableImageGeneration ?? input.enableMedia)
            : (input.enableVideoGeneration ?? input.enableMedia),
        ),
      }));
      const mapping = await metrics.measure('media', () =>
        generateMediaForClassroom(mediaOutlines, stage.id, baseUrl, { signal }),
      );
      await check();
      replaceMediaPlaceholders(scenes, mapping);
    }
    await mutateCourseJob(jobId, async (job) => {
      if (!isActiveCourseJob(job.status)) return job;
      stage.generationPlan!.complete = true;
      await snapshot();
      await saveCourseArtifact({
        id: `artifact_${jobId}`,
        jobId,
        teacherId,
        courseId: job.courseId,
        scope: job.scope,
        type: 'lesson-courseware',
        title: stage.name,
        status: 'review',
        citations: [],
        content: `互动课件已完整生成，共 ${scenes.length} 页。\n\n课堂地址：/classroom/${stage.id}`,
        classroomId: stage.id,
        classroomUrl: `/classroom/${stage.id}`,
        createdAt: job.createdAt,
        updatedAt: Date.now(),
      });
      return {
        ...job,
        status: 'review',
        progress: 100,
        error: undefined,
        artifactId: `artifact_${jobId}`,
        message: '课件已生成，返回工作区查看，满意后发布',
        backgroundGeneration: {
          ...progress(job, 'completed'),
          performance: performanceSnapshot(true),
        },
      };
    });
    if ((await readCourseJob(jobId))?.status === 'review') {
      await Promise.all(
        outlines.map((outline) => fs.unlink(checkpointPath(outline.order)).catch(() => undefined)),
      );
      await fs
        .unlink(path.join(CLASSROOM_JOBS_DIR, `${jobId}.courseware-input.json`))
        .catch(() => undefined);
    }
  } catch (error) {
    await mutateCourseJob(jobId, (job) =>
      isActiveCourseJob(job.status)
        ? {
            ...job,
            status: 'failed',
            message: '生成中断，已完成页面保留，可重试未完成步骤',
            error: error instanceof Error ? error.message : String(error),
          }
        : job,
    ).catch(() => undefined);
  } finally {
    if (heartbeat) clearInterval(heartbeat);
    release?.();
    await mutateCourseJob(jobId, (job) =>
      job.backgroundGeneration
        ? {
            ...job,
            backgroundGeneration: {
              ...job.backgroundGeneration,
              performance: performanceSnapshot(true),
            },
          }
        : job,
    ).catch(() => undefined);
  }
}
