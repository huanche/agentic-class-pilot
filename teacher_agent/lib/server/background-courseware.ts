import { promises as fs } from 'node:fs';
import path from 'node:path';
import { withGenerationRetry } from '@openmaic/generation';
import type { BackgroundCoursewareInput } from '@/lib/generation/background-courseware';
import { isActiveCourseJob } from '@/lib/generation/background-courseware';
import type { CourseArtifactJob } from '@/lib/course-space/types';
import type { Scene } from '@/lib/types/stage';
import type { DurationFeedback } from '@/lib/generation/course-duration';
import { calibrateNarrationDuration } from '@/lib/generation/course-duration';
import {
  calibrateCourseDuration,
  MAX_COURSE_DURATION_CORRECTIONS,
} from '@/lib/generation/course-duration-calibration';
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
import {
  readCourseJob,
  saveCourseJob,
  updateCourseJob,
  mutateCourseJob,
  saveCourseArtifact,
} from './course-space-storage';
import { internalPlatformHeaders } from './platform-auth';
import { fetchPlatformUserModelConfig } from './platform-user-model-config';
import {
  generateTTSForClassroom,
  finalizeClassroomTtsAudio,
  removeClassroomTtsAudio,
  generateMediaForClassroom,
  replaceMediaPlaceholders,
} from './classroom-media-generation';

// A shared registry also prevents duplicate workers across Next route bundles/HMR.
const root = globalThis as typeof globalThis & {
  __coursewareWorkers?: Map<string, { controller: AbortController; promise: Promise<void> }>;
  __coursewareSubmissions?: Map<string, Promise<unknown>>;
  __coursewareSlots?: { active: number; waiting: Set<() => void> };
};
const workers = (root.__coursewareWorkers ??= new Map());
const submissions = (root.__coursewareSubmissions ??= new Map());
const slots = (root.__coursewareSlots ??= { active: 0, waiting: new Set() });
const safeId = (id: string) => /^[A-Za-z0-9_-]{1,100}$/.test(id);

type StoredInput = { input: BackgroundCoursewareInput; baseUrl: string; teacherId: string };
function inputFile(jobId: string) {
  if (!/^[A-Za-z0-9_-]{1,110}$/.test(jobId)) throw new Error('无效任务编号');
  return path.join(CLASSROOM_JOBS_DIR, `${jobId}.courseware-input.json`);
}

async function acquireSlot(signal: AbortSignal) {
  const configured = Number(process.env.COURSEWARE_JOB_CONCURRENCY || 2);
  const limit = Number.isSafeInteger(configured) && configured > 0 ? Math.min(configured, 8) : 2;
  while (slots.active >= limit) {
    signal.throwIfAborted();
    await new Promise<void>((resolve, reject) => {
      const cleanup = () => {
        slots.waiting.delete(wake);
        signal.removeEventListener('abort', abort);
      };
      const wake = () => {
        cleanup();
        resolve();
      };
      const abort = () => {
        cleanup();
        reject(signal.reason);
      };
      slots.waiting.add(wake);
      signal.addEventListener('abort', abort, { once: true });
    });
  }
  signal.throwIfAborted();
  slots.active++;
  return () => {
    slots.active--;
    for (const wake of slots.waiting) wake();
  };
}

export async function createBackgroundCoursewareJob(
  input: BackgroundCoursewareInput,
  context: {
    courseId: string;
    teacherId: string;
    scope: CourseArtifactJob['scope'];
    baseUrl: string;
  },
) {
  if (!safeId(input.sessionId) || !safeId(input.stage.id)) throw new Error('无效生成会话');
  // Idempotency across double-clicks and a lost POST response after acceptance.
  const jobId = `cw_${input.sessionId}`;
  const existingSubmission = submissions.get(jobId);
  if (existingSubmission) {
    const pendingJob = (await existingSubmission) as CourseArtifactJob;
    if (pendingJob.courseId !== context.courseId || pendingJob.teacherId !== context.teacherId)
      throw new Error('任务归属不一致');
    return pendingJob;
  }
  const pending = (async () => {
    const existing = await readCourseJob(jobId);
    if (existing) {
      if (existing.courseId !== context.courseId || existing.teacherId !== context.teacherId)
        throw new Error('任务归属不一致');
      return existing;
    }
    if (!input.outlines?.length) throw new Error('请先确认课件大纲');
    if (input.preferImportedCanvas) {
      for (const outline of input.outlines) {
        if (outline.type !== 'slide' || input.formulaEnhancedOrders?.includes(outline.order))
          continue;
        const canvas = input.importedSlides?.[outline.order - 1];
        if (
          !canvas?.theme ||
          !Array.isArray(canvas.elements) ||
          !(canvas.viewportSize > 0) ||
          !(canvas.viewportRatio > 0)
        )
          throw new Error('PPT 画布不完整，请重新导入并确认页面');
      }
    }
    const orders = input.outlines.map((outline) => outline.order);
    if (
      new Set(orders).size !== orders.length ||
      orders.some((order) => !Number.isSafeInteger(order) || order < 1)
    )
      throw new Error('大纲页序无效');
    const occupied = await readClassroom(input.stage.id);
    if (occupied) throw new Error('课堂编号已使用，请重新创建生成会话');
    const now = Date.now();
    await writeJsonFileAtomic(inputFile(jobId), {
      input,
      baseUrl: context.baseUrl,
      teacherId: context.teacherId,
    } satisfies StoredInput);
    return saveCourseJob({
      id: jobId,
      courseId: context.courseId,
      teacherId: context.teacherId,
      scope: context.scope,
      artifactType: 'lesson-courseware',
      status: 'queued',
      progress: 0,
      message: '已提交服务器，等待生成',
      createdAt: now,
      updatedAt: now,
      backgroundGeneration: {
        classroomId: input.stage.id,
        completedPages: 0,
        totalPages: input.outlines.length,
        phase: 'queued',
      },
    });
  })();
  submissions.set(jobId, pending);
  try {
    return await pending;
  } finally {
    if (submissions.get(jobId) === pending) submissions.delete(jobId);
  }
}

export async function cancelBackgroundCoursewareJob(jobId: string) {
  const job = await mutateCourseJob(jobId, (current) => {
    if (!current.backgroundGeneration) throw new Error('此任务不支持取消');
    if (!isActiveCourseJob(current.status)) return current;
    return { ...current, status: 'cancelled', message: '已取消；已生成页面保留，后续页面不再生成' };
  });
  if (job.status === 'cancelled') {
    workers.get(jobId)?.controller.abort();
    await fs.unlink(inputFile(jobId)).catch(() => undefined);
  }
  return job;
}

/** Detached from the browser request. A cancelled/read-only visit never starts a worker. */
export function runBackgroundCoursewareJob(
  jobId: string,
  requestHeaders: Record<string, string> = {},
) {
  const active = workers.get(jobId);
  if (active) return active.promise;
  const controller = new AbortController();
  const promise = execute(jobId, controller, requestHeaders).finally(() => workers.delete(jobId));
  workers.set(jobId, { controller, promise });
  return promise;
}

async function execute(
  jobId: string,
  controller: AbortController,
  requestHeaders: Record<string, string>,
) {
  const signal = controller.signal;
  let heartbeat: ReturnType<typeof setInterval> | undefined;
  let releaseSlot: (() => void) | undefined;
  let stored: StoredInput | undefined;
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
  try {
    await check();
    heartbeat = setInterval(() => {
      void check()
        .then(() => updateCourseJob(jobId, {}))
        .catch(() => controller.abort());
    }, 10_000);
    releaseSlot = await acquireSlot(signal);
    await check();
    stored = JSON.parse(await fs.readFile(inputFile(jobId), 'utf8')) as StoredInput;
    const { input, baseUrl, teacherId } = stored;
    const { stage, outlines } = input;
    stage.generationModelPolicy = 'server';
    stage.generationPlan = { version: 1, outlines, complete: false, serverJobId: jobId };
    const saved = await readClassroom(stage.id);
    scenes = saved?.scenes ?? [];
    if (saved?.stage.timing) stage.timing = saved.stage.timing;
    const snapshot = () => {
      stage.updatedAt = Date.now();
      return persistClassroom({ id: stage.id, stage, scenes }, baseUrl);
    };
    const report = async (phase: string, message: string, progress: number) => {
      await check();
      const job = await updateCourseJob(jobId, {
        status: 'running',
        progress,
        message,
        backgroundGeneration: {
          classroomId: stage.id,
          completedPages: scenes.length,
          totalPages: outlines.length,
          phase,
        },
      });
      if (!isActiveCourseJob(job.status)) {
        controller.abort();
        signal.throwIfAborted();
      }
    };
    await report('starting', '服务器开始生成，可安全离开此页面', 1);
    await snapshot();
    // Keys are fetched/held only in memory, never written to the task file.
    const modelConfig =
      process.env.PLATFORM_AUTH_ENABLED === 'true'
        ? await fetchPlatformUserModelConfig(teacherId)
        : undefined;
    const headers = {
      'content-type': 'application/json',
      ...requestHeaders,
      ...internalPlatformHeaders(teacherId),
    };
    const request = async <T>(endpoint: string, body: unknown): Promise<T> =>
      withGenerationRetry(
        async () => {
          await check();
          const response = await fetch(`${baseUrl}${endpoint}`, {
            method: 'POST',
            headers,
            body: JSON.stringify(body),
            signal: AbortSignal.any([signal, AbortSignal.timeout(300_000)]),
          });
          const result = await response.json();
          await check();
          if (!response.ok || result.success === false) {
            const error = new Error(result.error || `生成服务返回 ${response.status}`);
            Object.assign(error, { statusCode: response.status });
            throw error;
          }
          return result as T;
        },
        { signal, maxRetries: 2, label: endpoint },
      );
    const actions = async (
      outline: (typeof outlines)[number],
      content: unknown,
      feedback?: DurationFeedback,
    ) => {
      const previous = scenes
        .filter((page) => page.order < outline.order)
        .sort((a, b) => b.order - a.order)[0];
      const result = await request<{ scene: Scene }>('/api/generate/scene-actions', {
        outline,
        allOutlines: outlines,
        content,
        stageId: stage.id,
        agents: input.agents,
        previousSpeeches:
          previous?.actions
            ?.filter((action) => action.type === 'speech')
            .map((action) => action.text) ?? [],
        languageDirective: stage.languageDirective,
        userProfile:
          input.requirements.userNickname || input.requirements.userBio
            ? `Student: ${input.requirements.userNickname || 'Unknown'} — ${input.requirements.userBio || ''}`
            : undefined,
        narrationScript: input.narrationScripts?.[outline.order - 1],
        durationFeedback: feedback,
      });
      return result.scene;
    };
    const audio = async (scene: Scene) => {
      if (!input.enableTTS || !scene.actions?.some((action) => action.type === 'speech')) return;
      await check();
      let result;
      try {
        result = await generateTTSForClassroom([scene], stage.id, baseUrl, modelConfig?.tts, {
          isolateAudio: true,
          failFast: true,
          recordUsage: true,
          voiceSelection: input.ttsVoice,
          languageDirective: stage.languageDirective,
          signal,
        });
      } catch (error) {
        await removeClassroomTtsAudio(scene, stage.id);
        throw error;
      }
      await check();
      if (result.failed || (!result.generated && result.skipped))
        throw new Error('配音未完成，请检查语音服务配置后重试');
    };
    const dispose = (scene: Scene) => removeClassroomTtsAudio(scene, stage.id);
    const regenerate = async (previous: Scene, feedback: DurationFeedback) => {
      const outline = outlines.find((page) => page.order === previous.order)!;
      const candidate = await actions(outline, previous.content, feedback);
      candidate.id = previous.id;
      candidate.timing = {
        ...previous.timing,
        measuredDurationSec: undefined,
        measurementKey: undefined,
      };
      try {
        await audio(candidate);
        return candidate;
      } catch (error) {
        await dispose(candidate);
        throw error;
      }
    };
    for (const outline of outlines) {
      await check();
      if (scenes.some((page) => page.order === outline.order)) continue;
      const progress = 3 + Math.floor((scenes.length / outlines.length) * 82);
      await report(
        'content',
        `第 ${scenes.length + 1}/${outlines.length} 页：生成页面内容`,
        progress,
      );
      const imported = input.importedSlides?.[outline.order - 1];
      const content =
        input.preferImportedCanvas &&
        imported &&
        !input.formulaEnhancedOrders?.includes(outline.order)
          ? { type: 'slide', canvas: imported }
          : (
              await request<{ content: unknown }>('/api/generate/scene-content', {
                outline,
                allOutlines: outlines,
                stageId: stage.id,
                stageInfo: { name: stage.name, description: stage.description, style: stage.style },
                requirements: input.requirements,
                agents: input.agents,
                pdfImages: input.pdfImages,
                imageMapping: input.imageMapping,
                languageDirective: stage.languageDirective,
              })
            ).content;
      await report(
        'actions',
        `第 ${scenes.length + 1}/${outlines.length} 页：生成讲解与聚焦`,
        progress + 1,
      );
      let scene = await actions(outline, content);
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
      await report(
        input.enableTTS ? 'audio' : 'saving-page',
        `第 ${scenes.length + 1}/${outlines.length} 页：${input.enableTTS ? '生成配音并核对时长' : '保存页面'}`,
        progress + 2,
      );
      await audio(scene);
      if (input.enableTTS && outline.durationBudget) {
        scene = await calibrateNarrationDuration(scene, {
          regenerate: (feedback, previous) => regenerate(previous, feedback),
          dispose,
        });
      }
      await check();
      await finalizeClassroomTtsAudio(scene, stage.id, baseUrl);
      scenes.push(scene);
      scenes.sort((a, b) => a.order - b.order);
      await snapshot();
      await report(
        'page-complete',
        `已完成 ${scenes.length}/${outlines.length} 页`,
        3 + Math.floor((scenes.length / outlines.length) * 82),
      );
    }
    if (input.enableMedia && outlines.some((outline) => outline.mediaGenerations?.length)) {
      await report('media', '生成课件中的图片与视频素材', 86);
      const mediaOutlines = outlines.map((outline) => ({
        ...outline,
        mediaGenerations: outline.mediaGenerations?.filter((request) =>
          request.type === 'image'
            ? (input.enableImageGeneration ?? input.enableMedia)
            : (input.enableVideoGeneration ?? input.enableMedia),
        ),
      }));
      const mapping = await generateMediaForClassroom(mediaOutlines, stage.id, baseUrl, { signal });
      await check();
      replaceMediaPlaceholders(scenes, mapping);
      await snapshot();
    }
    if (input.enableTTS && stage.timing?.targetDurationMinutes) {
      await report('duration', '汇总并校正整课实测时长', 92);
      const used = stage.timing.courseCorrectionAttempts ?? 0;
      const calibrated = await calibrateCourseDuration(
        scenes,
        stage.timing.targetDurationMinutes,
        stage.timing.expectedAutomaticPages ?? 0,
        {
          regenerate,
          dispose,
          onAttempt: async (attempt) => {
            stage.timing!.courseCorrectionAttempts = used + attempt;
            await snapshot();
          },
          onAccepted: async (previous, candidate) => {
            await check();
            await finalizeClassroomTtsAudio(candidate, stage.id, baseUrl);
            scenes = scenes.map((page) => (page.id === previous.id ? candidate : page));
            await snapshot();
          },
        },
        { maxAttempts: MAX_COURSE_DURATION_CORRECTIONS - used },
      );
      scenes = calibrated.scenes;
    }
    await check();
    await report('saving', '保存完整课件到课程文件夹', 98);
    // Finishing and cancelling use one lock: only one can win, and a cancelled
    // task never publishes a late artifact or switches back to completed.
    await mutateCourseJob(jobId, async (job) => {
      if (!isActiveCourseJob(job.status)) return job;
      stage.generationPlan!.complete = true;
      await snapshot();
      const artifactId = `artifact_${jobId}`;
      const now = Date.now();
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
        content: `互动课件已完整生成，共 ${scenes.length} 页。\n\n课堂地址：/classroom/${stage.id}`,
        classroomId: stage.id,
        classroomUrl: `/classroom/${stage.id}`,
        createdAt: now,
        updatedAt: now,
      });
      return {
        ...job,
        status: 'review',
        progress: 100,
        message: '完整课件已生成，等待教师审核',
        artifactId,
        backgroundGeneration: {
          classroomId: stage.id,
          completedPages: scenes.length,
          totalPages: outlines.length,
          phase: 'completed',
        },
      };
    });
    await fs.unlink(inputFile(jobId)).catch(() => undefined);
  } catch (error) {
    const current = await readCourseJob(jobId);
    if (current && isActiveCourseJob(current.status)) {
      await updateCourseJob(jobId, {
        status: 'failed',
        message: '生成中断，已完成的页面已保留',
        error: error instanceof Error ? error.message : String(error),
      });
    }
  } finally {
    if (heartbeat) clearInterval(heartbeat);
    releaseSlot?.();
  }
}
