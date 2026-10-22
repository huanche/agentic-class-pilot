'use client';

import { Sparkles } from 'lucide-react';
import { Button } from '@/components/ui/button';
import type { CourseArtifactJob } from '@/lib/course-space';
import { CoursewarePerformanceDetails } from './courseware-performance-details';
import {
  COURSE_JOB_STATUS_LABELS,
  isActiveCourseJob,
} from '@/lib/generation/background-courseware';

export function CourseJobProgress({
  job,
  cancelling,
  retrying,
  onCancel,
  onRetry,
  onView,
}: {
  job?: CourseArtifactJob;
  cancelling: boolean;
  retrying: boolean;
  onCancel: () => void;
  onRetry: () => void;
  onView: () => void;
}) {
  const courseware = job?.artifactType === 'lesson-courseware';
  const complete = courseware && (job.status === 'review' || job.status === 'approved');
  const active = job && isActiveCourseJob(job.status);
  const progress = complete ? 100 : job?.progress || 0;
  return (
    <div className="rounded-2xl border bg-white p-8 shadow-sm">
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h2 className="text-2xl font-semibold">
            {!job
              ? '正在读取任务'
              : complete
                ? '课件已生成'
                : job.status === 'cancelled'
                  ? '任务已取消'
                  : job.status === 'failed'
                    ? job.backgroundGeneration?.failedPages?.length
                      ? '部分页面待重试'
                      : '生成已中断'
                    : courseware
                      ? '正在生成课件'
                      : '正在生成单个教学产物'}
          </h2>
          <p className="mt-2 text-muted-foreground">
            {complete
              ? '返回工作区逐页查看、试听和修改，满意后发布课件。'
              : job?.message || '正在读取已保存的进度…'}
          </p>
          {job?.backgroundGeneration && (
            <p className="mt-2 text-sm text-muted-foreground">
              已完成 {job.backgroundGeneration.completedPages}/{job.backgroundGeneration.totalPages}{' '}
              页。
              {active && '可以关闭页面，回来后从“…”里的“任务记录”查看进度。'}
            </p>
          )}
        </div>
        <Sparkles className="size-8 text-violet-500" />
      </div>
      <div
        className="h-3 overflow-hidden rounded-full bg-slate-100"
        role="progressbar"
        aria-label="课件生成进度"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={progress}
      >
        <div
          className="h-full rounded-full bg-gradient-to-r from-blue-500 to-violet-600 transition-all"
          style={{ width: `${progress}%` }}
        />
      </div>
      <div className="mt-3 flex justify-between text-sm">
        <span>{complete ? '生成完成' : job ? COURSE_JOB_STATUS_LABELS[job.status] : '读取中'}</span>
        <span>{progress}%</span>
      </div>
      {job?.error && (
        <div className="mt-5 rounded-lg bg-red-50 p-3 text-sm text-red-700">{job.error}</div>
      )}
      {!!job?.backgroundGeneration?.failedPages?.some((page) => page.issues.length) && (
        <details className="mt-3 text-sm text-muted-foreground">
          <summary className="cursor-pointer">查看失败详情</summary>
          {job.backgroundGeneration.failedPages.map((page) => (
            <div key={page.order} className="mt-2">
              <p>
                第 {page.order} 页：{page.title}
              </p>
              <ul className="list-inside list-disc">
                {page.issues.map((issue, index) => (
                  <li key={index}>{issue}</li>
                ))}
              </ul>
            </div>
          ))}
        </details>
      )}
      <div className="mt-6 flex flex-wrap gap-3">
        {job?.backgroundGeneration && job.status === 'failed' && (
          <Button disabled={retrying} onClick={onRetry}>
            {retrying ? '正在提交重试…' : '重试未完成页面'}
          </Button>
        )}
        {job?.backgroundGeneration && active && (
          <Button variant="outline" disabled={cancelling} onClick={onCancel}>
            {cancelling ? '正在取消…' : '取消未完成任务'}
          </Button>
        )}
        <Button variant={complete ? 'default' : 'outline'} onClick={onView}>
          返回工作区查看
        </Button>
      </div>
      <CoursewarePerformanceDetails value={job?.backgroundGeneration?.performance} />
    </div>
  );
}
