import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { promises as fs } from 'node:fs';
import path from 'node:path';
import type { CourseArtifactJob } from '@/lib/course-space/types';
import type { BackgroundCoursewareInput } from '@/lib/generation/background-courseware';
import type { Scene } from '@/lib/types/stage';

const state = vi.hoisted(() => ({
  jobs: new Map<string, CourseArtifactJob>(),
  snapshots: new Map<string, { stage: unknown; scenes: unknown[] }>(),
  artifacts: vi.fn(),
  audio: vi.fn(),
  dispose: vi.fn(),
  content: vi.fn(),
  actions: vi.fn(),
  snapshotHook: undefined as undefined | ((snapshot: { scenes: unknown[] }) => Promise<void>),
}));
vi.mock('@/lib/server/course-space-storage', () => ({
  readCourseJob: async (id: string) => state.jobs.get(id) ?? null,
  saveCourseJob: async (job: CourseArtifactJob) => {
    state.jobs.set(job.id, job);
    return job;
  },
  updateCourseJob: async (id: string, patch: Partial<CourseArtifactJob>) => {
    const job = state.jobs.get(id)!;
    if (job.status === 'cancelled') return job;
    const next = { ...job, ...patch };
    state.jobs.set(id, next);
    return next;
  },
  mutateCourseJob: async (
    id: string,
    fn: (job: CourseArtifactJob) => Promise<CourseArtifactJob>,
  ) => {
    const next = await fn(state.jobs.get(id)!);
    state.jobs.set(id, next);
    return next;
  },
  saveCourseArtifact: state.artifacts,
}));
vi.mock('@/lib/server/classroom-storage', async () => {
  const original = await vi.importActual<typeof import('@/lib/server/classroom-storage')>(
    '@/lib/server/classroom-storage',
  );
  return {
    ...original,
    CLASSROOM_JOBS_DIR: path.join(process.cwd(), '.runtime', 'background-task-tests'),
    readClassroom: async (id: string) => state.snapshots.get(id) ?? null,
    persistClassroom: async (snapshot: { id: string; stage: unknown; scenes: unknown[] }) => {
      state.snapshots.set(snapshot.id, structuredClone(snapshot));
      await state.snapshotHook?.(snapshot);
      return snapshot;
    },
  };
});
vi.mock('@/lib/server/classroom-media-generation', () => ({
  generateTTSForClassroom: state.audio,
  finalizeClassroomTtsAudio: vi.fn(),
  removeClassroomTtsAudio: state.dispose,
  generateMediaForClassroom: vi.fn(async () => ({})),
  replaceMediaPlaceholders: vi.fn(),
}));
vi.mock('@/lib/server/platform-user-model-config', () => ({
  fetchPlatformUserModelConfig: vi.fn(),
}));
vi.mock('@/lib/server/platform-auth', () => ({ internalPlatformHeaders: () => ({}) }));
vi.mock('@/lib/server/openmaic-courseware-steps', () => ({
  createOpenmaicCoursewareSteps: () => ({ content: state.content, actions: state.actions }),
}));

import {
  createBackgroundCoursewareJob,
  runBackgroundCoursewareJob,
  cancelBackgroundCoursewareJob,
  retryBackgroundCoursewareJob,
} from '@/lib/server/background-courseware';

function input(sessionId: string): BackgroundCoursewareInput {
  return {
    sessionId,
    stage: {
      id: `stage_${sessionId}`,
      name: '后台生成测试',
      createdAt: 1,
      updatedAt: 1,
    } as BackgroundCoursewareInput['stage'],
    outlines: [1, 2].map((order) => ({
      id: `outline${order}`,
      type: 'slide',
      title: `第${order}页`,
      description: '加法示例',
      keyPoints: [],
      order,
    })),
    requirements: { requirement: '讲解简单加法' } as BackgroundCoursewareInput['requirements'],
    agents: [],
    enableTTS: false,
    enableMedia: false,
  };
}
const context = {
  courseId: 'course',
  teacherId: 'teacher',
  scope: { type: 'course' as const },
  baseUrl: 'http://server',
};
function response(value: unknown) {
  return new Response(JSON.stringify({ success: true, ...(value as object) }));
}
function fakeGeneration(url: string, init: RequestInit) {
  const body = JSON.parse(init.body as string);
  return Promise.resolve(
    url.endsWith('scene-content')
      ? response({ content: { elements: [] } })
      : response({
          scene: {
            id: `scene${body.outline.order}`,
            stageId: body.stageId,
            type: 'slide',
            order: body.outline.order,
            title: body.outline.title,
            content: { type: 'slide', canvas: { elements: [] } },
            actions: [],
          },
        }),
  );
}
beforeEach(() => {
  state.jobs.clear();
  state.snapshots.clear();
  state.artifacts.mockReset();
  state.audio.mockReset();
  state.dispose.mockReset();
  state.content.mockReset();
  state.actions.mockReset();
  state.snapshotHook = undefined;
  vi.stubEnv('PLATFORM_AUTH_ENABLED', 'false');
  vi.stubEnv('COURSEWARE_GENERATION_ENGINE', 'legacy');
  vi.stubGlobal('fetch', vi.fn(fakeGeneration));
});
afterEach(async () => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  const directory = path.resolve(process.cwd(), '.runtime', 'background-task-tests');
  if (!directory.startsWith(path.resolve(process.cwd(), '.runtime') + path.sep))
    throw new Error('Unsafe test path');
  await fs.rm(directory, { recursive: true, force: true });
});

describe('server-owned courseware generation', () => {
  it.each(['missing', 'malformed', 'incomplete'])(
    'settles a %s persisted plan as failed instead of leaving a stuck running task',
    async (problem) => {
      vi.stubEnv('COURSEWARE_GENERATION_ENGINE', 'openmaic');
      const job = await createBackgroundCoursewareJob(input(`plan_${problem}`), context);
      const plan = path.join(
        process.cwd(),
        '.runtime',
        'background-task-tests',
        `${job.id}.courseware-input.json`,
      );
      if (problem === 'missing') await fs.unlink(plan);
      else await fs.writeFile(plan, problem === 'malformed' ? '{' : '{}');
      await runBackgroundCoursewareJob(job.id);
      expect(state.jobs.get(job.id)).toMatchObject({
        status: 'failed',
        message: '无法读取生成计划，请重新创建任务',
      });
      expect(state.jobs.get(job.id)?.error).toBeTruthy();
      expect(fetch).not.toHaveBeenCalled();
      expect(state.audio).not.toHaveBeenCalled();
    },
  );
  it('opens the first OpenMAIC page while later pages generate and retries TTS without regenerating the models', async () => {
    vi.stubEnv('COURSEWARE_GENERATION_ENGINE', 'openmaic');
    const selected = input('openmaic_retry');
    selected.enableTTS = true;
    state.content.mockResolvedValue({ elements: [] });
    state.actions.mockImplementation(async (outline) => ({
      id: `s${outline.order}`,
      stageId: selected.stage.id,
      type: 'slide',
      order: outline.order,
      title: outline.title,
      content: { type: 'slide', canvas: { elements: [] } },
      actions: [{ id: 'speech', type: 'speech', text: '真实讲稿' }],
    }));
    state.audio
      .mockResolvedValueOnce({ generated: 1, failed: 0, skipped: 0 })
      .mockRejectedValueOnce(new Error('voice unavailable'));
    const job = await createBackgroundCoursewareJob(selected, context);
    await runBackgroundCoursewareJob(job.id);
    const partial = state.jobs.get(job.id)!;
    expect(partial.status).toBe('failed');
    expect(partial.artifactId).toBe(`artifact_${job.id}`);
    expect(partial.backgroundGeneration?.completedPages).toBe(1);
    expect(partial.backgroundGeneration?.performance?.engine).toBe('openmaic');
    expect(state.actions).toHaveBeenCalledTimes(2);
    state.audio.mockResolvedValue({ generated: 1, failed: 0, skipped: 0 });
    await retryBackgroundCoursewareJob(job.id);
    await runBackgroundCoursewareJob(job.id);
    expect(state.jobs.get(job.id)?.status).toBe('review');
    expect(state.content).toHaveBeenCalledTimes(2);
    expect(state.actions).toHaveBeenCalledTimes(2);
    expect(fetch).not.toHaveBeenCalled(); // Models are called in process, not through the public HTTP routes.
  });
  it('keeps committed OpenMAIC narration if cancellation wins after the first snapshot', async () => {
    vi.stubEnv('COURSEWARE_GENERATION_ENGINE', 'openmaic');
    const selected = input('openmaic_cancel');
    state.content.mockResolvedValue({ elements: [] });
    state.actions.mockImplementation(async (outline) => ({
      id: `s${outline.order}`,
      stageId: selected.stage.id,
      type: 'slide',
      order: outline.order,
      title: outline.title,
      content: { type: 'slide', canvas: { elements: [] } },
      actions: [],
    }));
    const job = await createBackgroundCoursewareJob(selected, context);
    state.content.mockImplementation(async (outline) => {
      if (outline.order === 2) await cancelBackgroundCoursewareJob(job.id);
      return { elements: [] };
    });
    await runBackgroundCoursewareJob(job.id);
    expect(state.jobs.get(job.id)?.status).toBe('cancelled');
    expect(state.snapshots.get(selected.stage.id)?.scenes).toHaveLength(1);
    expect(state.dispose).not.toHaveBeenCalled();
  });
  it('samples useful narration, repairs text before full TTS, then measures the accepted page', async () => {
    vi.stubEnv('COURSEWARE_NARRATION_BUDGET_ENABLED', 'true');
    const selected = input('script_budget');
    selected.enableTTS = true;
    selected.outlines = [{ ...selected.outlines[0], durationBudget: { targetSeconds: 20 } }];
    state.audio.mockImplementation(async (pages, _id, _base, _config, options) => {
      const page = pages[0];
      let seconds = 0;
      for (const action of page.actions)
        if (action.type === 'speech') {
          const duration = action.text.length / 5;
          seconds += duration;
          options?.onNarrationSample?.({
            identity: 'same-voice',
            text: action.text,
            seconds: duration,
          });
        }
      page.timing = { ...page.timing, measuredDurationSec: seconds };
      return { generated: 2, failed: 0, skipped: 0 };
    });
    vi.mocked(fetch).mockImplementation(async (url, init) => {
      const body = JSON.parse(init!.body as string);
      const generated = await (await fakeGeneration(String(url), init!)).json();
      if (generated.scene)
        generated.scene.actions = [
          { id: 'a', type: 'speech', text: '甲'.repeat(body.narrationRevision ? 80 : 30) },
          { id: 'b', type: 'speech', text: '乙'.repeat(20) },
        ];
      return response(generated);
    });
    const job = await createBackgroundCoursewareJob(selected, context);
    await runBackgroundCoursewareJob(job.id);
    expect(state.jobs.get(job.id)?.status).toBe('review');
    const calls = vi.mocked(fetch).mock.calls.map(([, init]) => JSON.parse(init!.body as string));
    const repair = calls.find((c) => c.narrationRevision);
    expect(repair.narrationPace).toEqual({ unitsPerSecond: 5, samples: 2 });
    expect(repair.narrationRevision.actions[0].text).toHaveLength(30);
    expect(repair.durationFeedback).toBeUndefined(); // Partial sampling is not a full-page measurement.
    expect(state.audio).toHaveBeenCalledTimes(2); // One probe, one full page; no whole-page correction.
    const saved = state.snapshots.get(selected.stage.id)!.scenes[0] as Scene;
    expect(saved.timing?.measuredDurationSec).toBe(20);
    expect(saved.timing?.correctionAttempts).toBe(0);
    const metrics = state.jobs.get(job.id)!.backgroundGeneration!.performance!;
    expect(metrics.timings.some((t) => t.phase === 'narration-probe')).toBe(true);
    expect(metrics.timings.some((t) => t.phase === 'script-budget')).toBe(true);
  });

  it('keeps an approved draft and its honest measured duration when local text repair is rejected', async () => {
    vi.stubEnv('COURSEWARE_NARRATION_BUDGET_ENABLED', 'true');
    const selected = input('script_budget_rejected');
    selected.enableTTS = true;
    selected.outlines = [{ ...selected.outlines[0], durationBudget: { targetSeconds: 20 } }];
    state.audio.mockImplementation(async (pages, _id, _base, _config, options) => {
      const page = pages[0];
      options?.onNarrationSample?.({
        identity: 'same-voice',
        text: page.actions[0].text,
        seconds: 10,
      });
      page.timing = { ...page.timing, measuredDurationSec: 10 };
      return { generated: 1, failed: 0, skipped: 0 };
    });
    vi.mocked(fetch).mockImplementation(async (url, init) => {
      const body = JSON.parse(init!.body as string);
      if (body.narrationRevision)
        return new Response(
          JSON.stringify({
            success: false,
            error: 'Rejected focus binding',
            errorCode: 'FOCUS_SPEECH_ALIGNMENT_FAILED',
          }),
          { status: 422 },
        );
      const generated = await (await fakeGeneration(String(url), init!)).json();
      if (generated.scene)
        generated.scene.actions = [{ id: 'a', type: 'speech', text: '甲'.repeat(50) }];
      return response(generated);
    });
    const job = await createBackgroundCoursewareJob(selected, context);
    await runBackgroundCoursewareJob(job.id);
    const saved = state.snapshots.get(selected.stage.id)!.scenes[0] as Scene;
    expect(saved.actions?.[0]).toMatchObject({ text: '甲'.repeat(50) });
    expect(saved.timing?.measuredDurationSec).toBe(10);
    expect(saved.timing?.durationStatus).toBe('too-short');
    expect(state.audio).toHaveBeenCalledTimes(2);
  });

  it('retains checkpoint audio when cancellation wins immediately after the page is saved', async () => {
    const selected = input('cancel_checkpoint');
    selected.enableTTS = true;
    state.audio.mockResolvedValue({ generated: 1, failed: 0, skipped: 0 });
    vi.mocked(fetch).mockImplementation(async (url, init) => {
      const generated = await (await fakeGeneration(String(url), init!)).json();
      if (generated.scene)
        generated.scene.actions = [{ id: 's', type: 'speech', text: '已完成配音' }];
      return response(generated);
    });
    const job = await createBackgroundCoursewareJob(selected, context);
    state.snapshotHook = async (snapshot) => {
      if (snapshot.scenes.length === 1) {
        state.snapshotHook = undefined;
        await cancelBackgroundCoursewareJob(job.id);
      }
    };
    await runBackgroundCoursewareJob(job.id);
    expect(state.jobs.get(job.id)?.status).toBe('cancelled');
    expect(state.snapshots.get(selected.stage.id)?.scenes).toHaveLength(1);
    expect(state.dispose).not.toHaveBeenCalled();
    expect(state.artifacts).not.toHaveBeenCalled();
    expect(state.jobs.get(job.id)?.backgroundGeneration?.performance?.finishedAt).toBeTypeOf(
      'number',
    );
  });

  it('does not publish an incomplete silent page after an audio provider failure', async () => {
    const selected = input('audio_failure');
    selected.enableTTS = true;
    state.audio.mockRejectedValue(new Error('TTS unavailable'));
    vi.mocked(fetch).mockImplementation(async (url, init) => {
      const generated = await (await fakeGeneration(String(url), init!)).json();
      if (generated.scene) generated.scene.actions = [{ id: 's', type: 'speech', text: '讲解' }];
      return response(generated);
    });
    const job = await createBackgroundCoursewareJob(selected, context);
    await runBackgroundCoursewareJob(job.id);
    expect(state.jobs.get(job.id)).toMatchObject({ status: 'failed', error: 'TTS unavailable' });
    expect(state.snapshots.get(selected.stage.id)?.scenes).toHaveLength(0);
    expect(state.artifacts).not.toHaveBeenCalled();
  });
  it('prepares the next page while the preceding audio runs, retaining narration order', async () => {
    const selected = input('overlap');
    selected.enableTTS = true;
    let release!: () => void;
    const audioBarrier = new Promise<void>((resolve) => {
      release = resolve;
    });
    let nextStarted!: () => void;
    const nextReady = new Promise<void>((resolve) => {
      nextStarted = resolve;
    });
    let firstAudioDone = false;
    state.audio.mockImplementation(async (pages) => {
      if (pages[0].order === 1) {
        await audioBarrier;
        firstAudioDone = true;
      }
      return { generated: 1, failed: 0, skipped: 0 };
    });
    vi.mocked(fetch).mockImplementation(async (url, init) => {
      const body = JSON.parse(init!.body as string);
      const generated = await (await fakeGeneration(String(url), init!)).json();
      if (generated.scene) {
        generated.scene.actions = [
          {
            id: 'speech' + body.outline.order,
            type: 'speech',
            text: '第' + body.outline.order + '页讲解',
          },
        ];
        if (body.outline.order === 2) {
          expect(firstAudioDone).toBe(false);
          expect(body.previousSpeeches).toEqual(['第1页讲解']);
          nextStarted();
        }
      }
      return response(generated);
    });
    const job = await createBackgroundCoursewareJob(selected, context);
    const running = runBackgroundCoursewareJob(job.id);
    await nextReady;
    release();
    await running;
    expect(state.jobs.get(job.id)).toMatchObject({
      status: 'review',
      backgroundGeneration: { performance: { pipeline: true, audioCache: { hits: 0 } } },
    });
    expect(state.snapshots.get(selected.stage.id)?.scenes).toMatchObject([
      { order: 1 },
      { order: 2 },
    ]);
    expect(state.jobs.get(job.id)?.backgroundGeneration?.performance?.firstPageReadyMs).toBeTypeOf(
      'number',
    );
  });

  it('re-plans speculative narration when preceding duration correction changes its words', async () => {
    const selected = input('corrected_context');
    selected.enableTTS = true;
    selected.outlines = selected.outlines.map((outline) => ({
      ...outline,
      durationBudget: { targetSeconds: 60 },
    }));
    let release!: () => void;
    const barrier = new Promise<void>((resolve) => {
      release = resolve;
    });
    let nextStarted!: () => void;
    const nextReady = new Promise<void>((resolve) => {
      nextStarted = resolve;
    });
    const contexts: string[][] = [];
    state.audio.mockImplementation(async (pages) => {
      const scene = pages[0];
      const original = scene.order === 1 && scene.actions[0].text === '原讲解';
      if (original) await barrier;
      scene.timing = { ...scene.timing, measuredDurationSec: original ? 1 : 60 };
      return { generated: 1, failed: 0, skipped: 0 };
    });
    vi.mocked(fetch).mockImplementation(async (url, init) => {
      const body = JSON.parse(init!.body as string);
      const generated = await (await fakeGeneration(String(url), init!)).json();
      if (generated.scene) {
        generated.scene.actions = [
          {
            id: 'speech' + body.outline.order,
            type: 'speech',
            text:
              body.outline.order === 1
                ? body.durationFeedback
                  ? '校时后的讲解'
                  : '原讲解'
                : '下一页讲解',
          },
        ];
        if (body.outline.order === 2) {
          contexts.push(body.previousSpeeches);
          nextStarted();
        }
      }
      return response(generated);
    });
    const job = await createBackgroundCoursewareJob(selected, context);
    const running = runBackgroundCoursewareJob(job.id);
    await nextReady;
    release();
    await running;
    expect(contexts).toEqual([['原讲解'], ['校时后的讲解']]);
    expect(state.jobs.get(job.id)?.status).toBe('review');
    expect(state.jobs.get(job.id)?.backgroundGeneration?.performance?.timings).toEqual(
      expect.arrayContaining([expect.objectContaining({ phase: 'context-repair', pageOrder: 2 })]),
    );
  });

  it('supports the serial rollback without changing page quality checks or audio order', async () => {
    vi.stubEnv('COURSEWARE_PIPELINE_ENABLED', 'false');
    const selected = input('serial');
    selected.enableTTS = true;
    const events: string[] = [];
    vi.mocked(fetch).mockImplementation(async (url, init) => {
      const body = JSON.parse(init!.body as string);
      events.push(
        `${String(url).endsWith('scene-content') ? 'content' : 'actions'}${body.outline.order}`,
      );
      const generated = await (await fakeGeneration(String(url), init!)).json();
      if (generated.scene) generated.scene.actions = [{ id: 's', type: 'speech', text: '讲解' }];
      return response(generated);
    });
    state.audio.mockImplementation(async (pages) => {
      events.push('audio' + pages[0].order);
      return { generated: 1, failed: 0, skipped: 0 };
    });
    const job = await createBackgroundCoursewareJob(selected, context);
    await runBackgroundCoursewareJob(job.id);
    expect(events).toEqual(['content1', 'actions1', 'audio1', 'content2', 'actions2', 'audio2']);
    expect(state.jobs.get(job.id)?.status).toBe('review');
  });

  it('keeps generating after a page alignment failure and retries only the missing page', async () => {
    const selected = input('alignment_retry');
    selected.outlines.push({ ...selected.outlines[1], id: 'outline3', order: 3 });
    vi.mocked(fetch).mockImplementation(async (url, init) => {
      const body = JSON.parse(init!.body as string);
      if (String(url).endsWith('scene-actions') && body.outline.order === 2)
        return new Response(
          JSON.stringify({
            success: false,
            errorCode: 'FOCUS_SPEECH_ALIGNMENT_FAILED',
            error: '讲解与聚焦校验未通过',
            details: 'speech 2: target does not match the example',
          }),
          { status: 422 },
        );
      return fakeGeneration(String(url), init!);
    });
    const job = await createBackgroundCoursewareJob(selected, context);
    await runBackgroundCoursewareJob(job.id);
    expect(state.snapshots.get(selected.stage.id)?.scenes).toMatchObject([
      { order: 1 },
      { order: 3 },
    ]);
    expect(state.jobs.get(job.id)).toMatchObject({
      status: 'failed',
      backgroundGeneration: {
        completedPages: 2,
        totalPages: 3,
        failedPages: [{ order: 2, issues: ['speech 2: target does not match the example'] }],
      },
    });
    expect(state.artifacts).not.toHaveBeenCalled();
    vi.mocked(fetch)
      .mockClear()
      .mockImplementation((url, init) => fakeGeneration(String(url), init!));
    await retryBackgroundCoursewareJob(job.id);
    await runBackgroundCoursewareJob(job.id);
    expect(fetch).toHaveBeenCalledTimes(2);
    for (const [, init] of vi.mocked(fetch).mock.calls)
      expect(JSON.parse(init!.body as string).outline.order).toBe(2);
    expect(state.jobs.get(job.id)).toMatchObject({
      status: 'review',
      backgroundGeneration: { completedPages: 3, failedPages: [] },
    });
    expect(state.artifacts).toHaveBeenCalledOnce();
  });

  it('does not restart completed or cancelled jobs as a retry', async () => {
    const job = await createBackgroundCoursewareJob(input('no_retry_cancelled'), context);
    await cancelBackgroundCoursewareJob(job.id);
    await expect(retryBackgroundCoursewareJob(job.id)).rejects.toThrow();
    expect(state.jobs.get(job.id)?.status).toBe('cancelled');
    expect(fetch).not.toHaveBeenCalled();
  });
  it('keeps the submitted voice for every page after the browser settings change', async () => {
    const selected = input('voice_snapshot');
    selected.enableTTS = true;
    selected.ttsVoice = { providerId: 'lemonade-tts', voice: 'zm_yunxi' };
    state.audio.mockResolvedValue({ generated: 1, failed: 0, skipped: 0 });
    vi.mocked(fetch).mockImplementation(async (url, init) => {
      const generated = await (await fakeGeneration(String(url), init!)).json();
      if (generated.scene)
        generated.scene.actions = [{ id: 'speech', type: 'speech', text: '现在观察加法示例。' }];
      return response(generated);
    });
    const job = await createBackgroundCoursewareJob(selected, context);
    selected.ttsVoice.voice = 'zf_xiaoyi';
    await runBackgroundCoursewareJob(job.id);
    expect(state.jobs.get(job.id)?.status).toBe('review');
    expect(state.audio).toHaveBeenCalledTimes(2);
    for (const call of state.audio.mock.calls)
      expect(call[4]).toMatchObject({
        voiceSelection: { providerId: 'lemonade-tts', voice: 'zm_yunxi' },
      });
  });

  it('does not share a concurrent submission across different owners', async () => {
    const first = createBackgroundCoursewareJob(input('owner_check'), context);
    const other = createBackgroundCoursewareJob(input('owner_check'), {
      ...context,
      courseId: 'other-course',
      teacherId: 'other-teacher',
    });
    await expect(other).rejects.toThrow('任务归属不一致');
    await first;
  });
  it('lets a queued task be cancelled without starting a provider call', async () => {
    vi.stubEnv('COURSEWARE_JOB_CONCURRENCY', '1');
    let firstStarted!: () => void;
    const started = new Promise<void>((resolve) => {
      firstStarted = resolve;
    });
    vi.mocked(fetch).mockImplementation(async (_url, init) => {
      firstStarted();
      return new Promise<Response>((_resolve, reject) => {
        init!.signal!.addEventListener(
          'abort',
          () => reject(new DOMException('Cancelled', 'AbortError')),
          { once: true },
        );
      });
    });
    const first = await createBackgroundCoursewareJob(input('queue_first'), context);
    const second = await createBackgroundCoursewareJob(input('queue_second'), context);
    const running = runBackgroundCoursewareJob(first.id);
    await started;
    const queued = runBackgroundCoursewareJob(second.id);
    await cancelBackgroundCoursewareJob(second.id);
    await queued;
    expect(fetch).toHaveBeenCalledTimes(2); // Only the running task's bounded lookahead.
    for (const [, init] of vi.mocked(fetch).mock.calls)
      expect(JSON.parse(init!.body as string).stageId).toBe(
        first.backgroundGeneration?.classroomId,
      );
    expect(state.jobs.get(second.id)?.status).toBe('cancelled');
    await cancelBackgroundCoursewareJob(first.id);
    await running;
  });
  it('persists acceptance and completes all pages without any browser polling', async () => {
    const job = await createBackgroundCoursewareJob(input('detached'), context);
    await runBackgroundCoursewareJob(job.id);
    expect(state.jobs.get(job.id)).toMatchObject({
      status: 'review',
      progress: 100,
      backgroundGeneration: { completedPages: 2, totalPages: 2 },
    });
    expect(state.snapshots.get('stage_detached')).toMatchObject({
      stage: { generationPlan: { complete: true, serverJobId: job.id } },
      scenes: [{ order: 1 }, { order: 2 }],
    });
    expect(state.artifacts).toHaveBeenCalledOnce();
  });

  it('accepts a repeated submit once and does not expose credentials in persisted input', async () => {
    const [first, second] = await Promise.all([
      createBackgroundCoursewareJob(input('duplicate'), context),
      createBackgroundCoursewareJob(input('duplicate'), context),
    ]);
    expect(first.id).toBe(second.id);
    expect(state.jobs.size).toBe(1);
    const contents = await fs.readFile(
      path.join(
        process.cwd(),
        '.runtime',
        'background-task-tests',
        `${first.id}.courseware-input.json`,
      ),
      'utf8',
    );
    expect(contents).not.toContain('apiKey');
    await cancelBackgroundCoursewareJob(first.id);
    await runBackgroundCoursewareJob(first.id);
    expect(fetch).not.toHaveBeenCalled();
    expect(state.jobs.get(first.id)?.status).toBe('cancelled');
  });

  it('aborts an in-flight generation, retains checkpoint pages and never publishes a cancelled task', async () => {
    const job = await createBackgroundCoursewareJob(input('cancel'), context);
    let secondPageStarted!: () => void;
    const started = new Promise<void>((resolve) => {
      secondPageStarted = resolve;
    });
    vi.mocked(fetch).mockImplementation(async (url, init) => {
      const body = JSON.parse(init!.body as string);
      if (body.outline.order === 2) {
        secondPageStarted();
        return new Promise<Response>((_resolve, reject) => {
          init!.signal!.addEventListener(
            'abort',
            () => reject(new DOMException('Cancelled', 'AbortError')),
            { once: true },
          );
        });
      }
      return fakeGeneration(String(url), init!);
    });
    const running = runBackgroundCoursewareJob(job.id);
    await started;
    await vi.waitFor(() => expect(state.snapshots.get('stage_cancel')?.scenes).toHaveLength(1));
    const cancelled = await cancelBackgroundCoursewareJob(job.id);
    await running;
    expect(cancelled.status).toBe('cancelled');
    expect(state.jobs.get(job.id)?.status).toBe('cancelled');
    expect(state.snapshots.get('stage_cancel')?.scenes).toHaveLength(1);
    expect(state.artifacts).not.toHaveBeenCalled();
    expect(fetch).toHaveBeenCalledTimes(3);
    await runBackgroundCoursewareJob(job.id);
    expect(fetch).toHaveBeenCalledTimes(3);
  });

  it('does not regenerate a completed checkpoint after a worker is started again', async () => {
    const job = await createBackgroundCoursewareJob(input('checkpoint'), context);
    state.snapshots.set('stage_checkpoint', {
      stage: {},
      scenes: [{ id: 'previous', order: 1, type: 'slide', actions: [] }],
    });
    await runBackgroundCoursewareJob(job.id);
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(state.jobs.get(job.id)?.status).toBe('review');
    await cancelBackgroundCoursewareJob(job.id);
    expect(state.jobs.get(job.id)?.status).toBe('review');
  });
});
