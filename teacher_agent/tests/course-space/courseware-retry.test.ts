// @vitest-environment jsdom
import { act, createElement, Fragment } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CoursewareGenerationButton } from '@/components/course-space/courseware-generation-button';
import { useCourseGenerationTask } from '@/lib/store/course-generation-task';
import type { CourseArtifactJob, CourseSpace } from '@/lib/course-space';

vi.mock('next/link', () => ({ default: 'a' }));
vi.mock('@/components/ui/popover', () => ({
  Popover: ({ children }: { children: React.ReactNode }) => createElement(Fragment, null, children),
  PopoverTrigger: ({ children }: { children: React.ReactNode }) => children,
  PopoverContent: ({ children }: { children: React.ReactNode }) =>
    createElement('div', null, children),
}));

const course = {
  id: 'course',
  title: 'C 语言',
  status: 'active',
  modules: [],
} as unknown as CourseSpace;
const failedJob = {
  id: 'original-job',
  courseId: course.id,
  artifactType: 'lesson-courseware',
  scope: { type: 'lesson', lessonId: 'lesson' },
  status: 'failed',
  progress: 40,
  createdAt: 1,
  message: '生成中断，已完成页面保留',
  artifactId: 'original-artifact',
  backgroundGeneration: { classroomId: 'original-classroom', completedPages: 2, totalPages: 5 },
} as CourseArtifactJob;

describe('workspace courseware retry', () => {
  let host: HTMLDivElement;
  let root: Root;
  const onGenerate = vi.fn();
  const onRefresh = vi.fn(async () => {});
  const onOpenResult = vi.fn();
  const fetchMock = vi.fn();
  const render = async (job = failedJob, extra = {}) => {
    await act(async () =>
      root.render(
        createElement(CoursewareGenerationButton, {
          course,
          lessonId: 'lesson',
          jobs: [job],
          generationLocked: false,
          onGenerate,
          onRefresh,
          onOpenResult,
          ...extra,
        }),
      ),
    );
  };
  const button = (text: string) =>
    Array.from(host.querySelectorAll('button')).find((item) => item.textContent === text);

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
    vi.stubGlobal('fetch', fetchMock);
    host = document.createElement('div');
    document.body.append(host);
    root = createRoot(host);
    useCourseGenerationTask.setState({ task: null, runtimeId: null });
  });
  afterEach(async () => {
    await act(async () => root.unmount());
    host.remove();
    vi.unstubAllGlobals();
  });

  it('resumes the same job without opening the new-courseware or outline flow', async () => {
    useCourseGenerationTask.getState().setTask({
      id: 'original-session',
      courseId: course.id,
      serverJobId: failedJob.id,
      title: 'C 语言',
      status: 'failed',
      message: failedJob.message,
      step: 2,
      total: 5,
    });
    const queued = { ...failedJob, status: 'queued', message: '等待重试未完成页面' };
    fetchMock.mockResolvedValue(Response.json({ success: true, job: queued }));
    await render();
    const retry = button('重试未完成页面');
    expect(retry).toBeDefined();
    await act(async () => retry!.click());
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith('/api/course-space/jobs/original-job', {
      method: 'PATCH',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ action: 'retry' }),
    });
    expect(onGenerate).not.toHaveBeenCalled();
    expect(onRefresh).toHaveBeenCalledOnce();
    expect(useCourseGenerationTask.getState().task).toMatchObject({
      id: 'original-session',
      serverJobId: failedJob.id,
      status: 'running',
      step: 2,
      total: 5,
    });
    await render(queued as CourseArtifactJob, { generationLocked: true });
    expect(button('排队中 40%')).toBeDefined();
    await act(async () => button('查看已生成页面')!.click());
    expect(onOpenResult).toHaveBeenCalledWith(
      expect.objectContaining({
        id: failedJob.id,
        artifactId: 'original-artifact',
        backgroundGeneration: expect.objectContaining({ classroomId: 'original-classroom' }),
      }),
    );
  });

  it('shows a retry rejection without silently creating a new courseware job', async () => {
    fetchMock.mockResolvedValue(
      Response.json({ success: false, error: '原生成计划已不存在' }, { status: 400 }),
    );
    await render();
    await act(async () => button('重试未完成页面')!.click());
    expect(host.querySelector('[role="alert"]')?.textContent).toBe('原生成计划已不存在');
    expect(onGenerate).not.toHaveBeenCalled();
    expect(onRefresh).not.toHaveBeenCalled();
    expect(button('重试未完成页面')?.disabled).toBe(false);
  });

  it('blocks repeat submissions while retry is pending and respects the generation lock', async () => {
    let resolve!: (response: Response) => void;
    fetchMock.mockReturnValue(
      new Promise<Response>((done) => {
        resolve = done;
      }),
    );
    await render();
    await act(async () => button('重试未完成页面')!.click());
    const pending = button('正在提交重试…');
    expect(pending?.disabled).toBe(true);
    await act(async () => pending!.click());
    expect(fetchMock).toHaveBeenCalledOnce();
    await act(async () =>
      resolve(Response.json({ success: true, job: { ...failedJob, status: 'queued' } })),
    );
    await render(failedJob, { generationLocked: true });
    expect(button('重试未完成页面')?.disabled).toBe(true);
    await render(failedJob, { course: { ...course, status: 'archived' } });
    expect(button('重试未完成页面')?.disabled).toBe(true);
  });

  it('labels jobs without a resumable server plan as new courseware', async () => {
    await render({ ...failedJob, backgroundGeneration: undefined });
    expect(button('重试未完成页面')).toBeUndefined();
    const start = button('新建课件');
    expect(start).toBeDefined();
    await act(async () => start!.click());
    expect(onGenerate).toHaveBeenCalledWith('lesson');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('does not replace the browser snapshot of a different job when resuming', async () => {
    const otherTask = {
      id: 'another-session',
      courseId: 'another-course',
      serverJobId: 'another-job',
      title: 'Another course',
      status: 'completed' as const,
      message: '生成完成',
      step: 5,
      total: 5,
    };
    useCourseGenerationTask.getState().setTask(otherTask);
    fetchMock.mockResolvedValue(
      Response.json({ success: true, job: { ...failedJob, status: 'queued' } }),
    );
    await render();
    await act(async () => button('重试未完成页面')!.click());
    expect(useCourseGenerationTask.getState().task).toEqual(otherTask);
    expect(onGenerate).not.toHaveBeenCalled();
  });

  it('keeps the normal new-courseware entry for lessons without a previous job', async () => {
    await render(failedJob, { jobs: [] });
    await act(async () => button('生成课件')!.click());
    expect(onGenerate).toHaveBeenCalledWith('lesson');
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
