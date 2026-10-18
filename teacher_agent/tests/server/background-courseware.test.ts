import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { promises as fs } from 'node:fs';
import path from 'node:path';
import type { CourseArtifactJob } from '@/lib/course-space/types';
import type { BackgroundCoursewareInput } from '@/lib/generation/background-courseware';

const state = vi.hoisted(() => ({
  jobs: new Map<string, CourseArtifactJob>(),
  snapshots: new Map<string, { stage: unknown; scenes: unknown[] }>(),
  artifacts: vi.fn(),
  audio: vi.fn(),
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
      return snapshot;
    },
  };
});
vi.mock('@/lib/server/classroom-media-generation', () => ({
  generateTTSForClassroom: state.audio,
  finalizeClassroomTtsAudio: vi.fn(),
  removeClassroomTtsAudio: vi.fn(),
  generateMediaForClassroom: vi.fn(async () => ({})),
  replaceMediaPlaceholders: vi.fn(),
}));
vi.mock('@/lib/server/platform-user-model-config', () => ({
  fetchPlatformUserModelConfig: vi.fn(),
}));
vi.mock('@/lib/server/platform-auth', () => ({ internalPlatformHeaders: () => ({}) }));

import {
  createBackgroundCoursewareJob,
  runBackgroundCoursewareJob,
  cancelBackgroundCoursewareJob,
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
  vi.stubEnv('PLATFORM_AUTH_ENABLED', 'false');
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
    expect(fetch).toHaveBeenCalledOnce();
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
