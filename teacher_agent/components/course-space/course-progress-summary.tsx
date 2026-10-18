'use client';
import {
  useCourseGenerationTask,
  isGenerationTaskActive,
} from '@/lib/store/course-generation-task';
import { ListTodo, ChevronRight, LoaderCircle } from 'lucide-react';
import type { CourseArtifactJob, CourseArtifactRecord, CourseSpace } from '@/lib/course-space';
import Link from 'next/link';
import {
  summarizeCourseProgress,
  type CourseStatusTarget,
} from '@/lib/course-space/course-progress';
export function CourseProgressSummary({
  course,
  artifacts,
  jobs = [],
  onFocus,
}: {
  course: CourseSpace;
  artifacts: CourseArtifactRecord[];
  jobs?: CourseArtifactJob[];
  onFocus: (target: CourseStatusTarget) => void;
}) {
  const progress = summarizeCourseProgress(course, artifacts);
  const task = useCourseGenerationTask((state) => state.task);
  const courseTask = task?.courseId === course.id && isGenerationTaskActive(task) ? task : null;
  const serverTask = jobs.find(
    (job) => job.backgroundGeneration && ['queued', 'running'].includes(job.status),
  );
  return (
    <div className="flex w-full flex-wrap items-center gap-x-5 gap-y-2 border-t border-slate-200/60 pt-2 text-xs">
      <div
        className="flex items-center gap-2"
        title="课次的课程目标、知识点及课件均审核通过后，计为备课完成。"
      >
        <span className="font-medium text-slate-700">课程进度</span>
        <div
          role="progressbar"
          aria-label="课次备课进度"
          aria-valuemin={0}
          aria-valuemax={progress.lessonTotal || 1}
          aria-valuenow={progress.prepared}
          aria-valuetext={`已完成备课${progress.prepared}个课次，共${progress.lessonTotal}个课次`}
          className="h-1.5 w-24 overflow-hidden rounded-full bg-slate-200"
        >
          <div
            className="h-full rounded-full bg-[#B00055]"
            style={{ width: `${progress.percent}%` }}
          />
        </div>
        <span className="text-slate-500">
          备课 {progress.prepared}/{progress.lessonTotal} 课次
        </span>
      </div>
      <button
        onClick={() => onFocus({ folder: 'materials' })}
        className="text-slate-500 hover:text-[#B00055]"
      >
        资料解析 {progress.materialReady}/{progress.materialTotal}
      </button>
      <button
        onClick={() => onFocus({ folder: 'outline' })}
        className={progress.outlineReady ? 'text-emerald-700' : 'text-amber-700'}
      >
        大纲{progress.outlineReady ? '已审核' : '待完成'}
      </button>
      <span className="text-slate-500">
        已发布 {progress.published}/{progress.lessonTotal} 课次
      </span>
      {serverTask ? (
        <Link
          href={`/course-space/${course.id}/jobs/${serverTask.id}`}
          role="status"
          className="flex items-center gap-1.5 text-[#B00055]"
        >
          <LoaderCircle className="size-3.5 animate-spin" />
          后台生成 {serverTask.backgroundGeneration!.completedPages}/
          {serverTask.backgroundGeneration!.totalPages} 页 · {serverTask.progress}%
        </Link>
      ) : (
        courseTask && (
          <span role="status" className="flex items-center gap-1.5 text-[#B00055]">
            <LoaderCircle className="size-3.5 animate-spin" />
            {courseTask.status === 'review'
              ? '生成任务待审核'
              : `正在生成 · 阶段${courseTask.step}/${courseTask.total}`}
          </span>
        )
      )}
      <details className="group relative ml-auto">
        <summary className="flex cursor-pointer list-none items-center gap-1.5 rounded-full border bg-white px-3 py-1.5 text-[#B00055]">
          <ListTodo className="size-3.5" />
          待办 {progress.todos.length} 项
          <ChevronRight className="size-3 transition group-open:rotate-90" />
        </summary>
        <div className="absolute right-0 top-full z-40 mt-2 w-80 max-w-[85vw] rounded-2xl border bg-white p-3 shadow-xl">
          <p className="mb-2 px-2 text-xs font-medium text-slate-700">当前课程待办</p>
          {progress.todos.length ? (
            progress.todos.map((todo) => (
              <button
                key={todo.title}
                onClick={(event) => {
                  onFocus(todo.target);
                  event.currentTarget.closest('details')?.removeAttribute('open');
                }}
                className="flex w-full items-center justify-between gap-3 rounded-lg px-2 py-2.5 text-left text-xs text-slate-600 hover:bg-[#B00055]/5 hover:text-[#B00055]"
              >
                <span>{todo.title}</span>
                <ChevronRight className="size-3 shrink-0" />
              </button>
            ))
          ) : (
            <p className="px-2 py-3 text-xs text-emerald-700">当前资料、备课和发布环节暂无待办。</p>
          )}
          <p className="mt-2 border-t px-2 pt-2 text-[10px] leading-5 text-slate-400">
            备课进度按目标、知识点与课件的实际审核状态统计。
          </p>
        </div>
      </details>
      {progress.todos[0] && (
        <button
          onClick={() => onFocus(progress.todos[0].target)}
          className="max-w-full truncate text-amber-700 hover:text-[#B00055]"
        >
          下一步：{progress.todos[0].title}
        </button>
      )}
    </div>
  );
}
