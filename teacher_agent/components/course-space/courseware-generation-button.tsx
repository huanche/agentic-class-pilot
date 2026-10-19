'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { Check, CircleAlert, LoaderCircle, Sparkles } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import type { CourseArtifactJob, CourseSpace } from '@/lib/course-space';
import { useCourseGenerationTask } from '@/lib/store/course-generation-task';
import {
  isCoursewareTaskRunning,
  resolveCoursewareTaskProgress,
} from '@/lib/course-space/courseware-task-progress';

export function CoursewareGenerationButton({
  course,
  lessonId,
  jobs,
  generationLocked,
  onGenerate,
  onRefresh,
  onOpenResult,
}: {
  course: CourseSpace;
  lessonId?: string;
  jobs: CourseArtifactJob[];
  generationLocked: boolean;
  onGenerate: (lessonId: string) => void;
  onRefresh: () => Promise<void>;
  onOpenResult: (job: CourseArtifactJob) => void;
}) {
  const task = useCourseGenerationTask((state) => state.task);
  const view = resolveCoursewareTaskProgress({ courseId: course.id, lessonId, jobs, task });
  const active = Boolean(view && isCoursewareTaskRunning(view.status));
  const [open, setOpen] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState('');
  const [completedId, setCompletedId] = useState<string>();
  const previous = useRef<{ id: string; active: boolean } | null>(null);
  const viewId = view?.id;
  const viewStatus = view?.status;
  useEffect(() => {
    setOpen(false);
    setError('');
  }, [viewId]);
  useEffect(() => {
    if (viewStatus === 'completed' && previous.current?.id === viewId && previous.current?.active) {
      setCompletedId(viewId);
    }
    previous.current = viewId ? { id: viewId, active } : null;
  }, [viewId, viewStatus, active]);
  useEffect(() => {
    if (!completedId) return;
    const timer = window.setTimeout(() => setCompletedId(undefined), 6000);
    return () => window.clearTimeout(timer);
  }, [completedId]);

  if (!lessonId && !active) return null;
  const failed = view?.status === 'failed';
  const completed = view?.status === 'completed' && completedId === view.id;
  const inspect = active || failed || completed;
  const job = view?.job;
  const scope = job?.scope;
  const courseModule = course.modules.find((item) =>
    scope?.type === 'module'
      ? item.id === scope.moduleId
      : scope?.type === 'lesson' && item.lessons.some((lesson) => lesson.id === scope.lessonId),
  );
  const lesson =
    scope?.type === 'lesson'
      ? courseModule?.lessons.find((item) => item.id === scope.lessonId)
      : undefined;
  const taskTitle = lesson
    ? `${courseModule?.title} / ${lesson.title}`
    : courseModule?.title || view?.task?.title || course.title;
  const label = failed
    ? '生成中断'
    : completed
      ? '生成完成'
      : view?.status === 'review'
        ? '等待确认'
        : active
          ? `${view?.status === 'queued' ? '排队中' : '生成中'} ${view?.progress}%`
          : '生成课件';
  const Icon = failed ? CircleAlert : completed ? Check : active ? LoaderCircle : Sparkles;
  const detailUrl = job
    ? `/course-space/${encodeURIComponent(course.id)}/jobs/${encodeURIComponent(job.id)}`
    : view?.task?.url;
  const cancel = async () => {
    if (!job || cancelling) return;
    setCancelling(true);
    setError('');
    try {
      const response = await fetch(`/api/course-space/jobs/${encodeURIComponent(job.id)}`, {
        method: 'PATCH',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ action: 'cancel' }),
      });
      const data = await response.json();
      if (!response.ok || data.success === false) throw new Error(data.error || '取消任务失败');
      // Also settle the browser snapshot; reopening this course must not show a stale spinner.
      const current = useCourseGenerationTask.getState().task;
      if (current?.serverJobId === job.id) {
        useCourseGenerationTask.getState().setTask({
          ...current,
          status: data.job.status === 'cancelled' ? 'cancelled' : 'completed',
          message: data.job.message,
        });
      }
      await onRefresh();
      setOpen(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setCancelling(false);
    }
  };
  return (
    <Popover open={open && Boolean(view)} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          size="sm"
          aria-label={label}
          disabled={!inspect && (generationLocked || !lessonId || course.status === 'archived')}
          title={
            inspect
              ? `查看生成任务：${taskTitle}`
              : generationLocked
                ? '请先完成或取消正在生成的任务'
                : '生成课件'
          }
          className={`relative overflow-hidden ${failed ? 'bg-red-700 hover:bg-red-800' : 'bg-[#B00055] hover:bg-[#8F0046]'}`}
          onClick={(event) => {
            if (inspect) return;
            event.preventDefault();
            if (lessonId) onGenerate(lessonId);
          }}
        >
          <Icon
            aria-hidden="true"
            className={`mr-1 size-3.5 ${active && view?.status !== 'review' ? 'animate-spin motion-reduce:animate-none' : ''}`}
          />
          {label}
          {active && (
            <span
              role="progressbar"
              aria-label="课件生成进度"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={view?.progress}
              aria-valuetext={`${label}，${view?.message}`}
              className="absolute inset-x-0 bottom-0 h-0.5 bg-white/25"
            >
              <span
                className="block h-full bg-white/90 transition-[width] motion-reduce:transition-none"
                style={{ width: `${view?.progress}%` }}
              />
            </span>
          )}
        </Button>
      </PopoverTrigger>
      {view && (
        <PopoverContent
          align="end"
          aria-label="当前课件生成任务"
          className="w-80 max-w-[calc(100vw-2rem)] rounded-xl p-4"
        >
          <p className="text-sm font-semibold">
            {active
              ? '课件生成进度'
              : failed
                ? '生成中断'
                : view.status === 'cancelled'
                  ? '任务已取消'
                  : '生成完成'}
          </p>
          <p className="mt-1 text-xs text-slate-500">{taskTitle}</p>
          <p className="mt-3 text-sm text-slate-700" role="status">
            {view.message}
          </p>
          {job?.backgroundGeneration && (
            <p className="mt-1 text-xs text-slate-500">
              已完成 {job.backgroundGeneration.completedPages}/{job.backgroundGeneration.totalPages}{' '}
              页
            </p>
          )}
          {active && job?.backgroundGeneration && (
            <p className="mt-2 text-xs text-slate-500">可离开页面，生成会在后台继续。</p>
          )}
          {failed && job?.error && (
            <p className="mt-2 break-words text-xs text-red-700">{job.error}</p>
          )}
          {error && (
            <p role="alert" className="mt-2 text-xs text-red-700">
              {error}
            </p>
          )}
          <div className="mt-4 flex flex-wrap gap-2">
            {job?.backgroundGeneration && active && (
              <Button
                size="sm"
                variant="outline"
                disabled={cancelling}
                onClick={() => void cancel()}
              >
                {cancelling ? '正在取消…' : '取消任务'}
              </Button>
            )}
            {job && view.status === 'completed' && job.artifactId && (
              <Button
                size="sm"
                className="bg-[#B00055] hover:bg-[#8F0046]"
                onClick={() => {
                  setOpen(false);
                  onOpenResult(job);
                }}
              >
                查看课件
              </Button>
            )}
            {failed && lessonId && (
              <Button
                size="sm"
                disabled={generationLocked || course.status === 'archived'}
                onClick={() => {
                  setOpen(false);
                  onGenerate(lessonId);
                }}
              >
                重新生成
              </Button>
            )}
            {detailUrl && (
              <Button size="sm" variant="ghost" asChild>
                <Link href={detailUrl}>{view.status === 'review' ? '继续确认' : '任务详情'}</Link>
              </Button>
            )}
          </div>
          {failed && lessonId && (
            <p className="mt-2 text-xs text-slate-500">重新生成会创建新课件，已生成页面仍保留。</p>
          )}
        </PopoverContent>
      )}
    </Popover>
  );
}
