'use client';

import { useCallback, useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { ArrowLeft, Check, Expand, Eye, LoaderCircle, Sparkles } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ArtifactHtmlReview } from '@/components/course-space/artifact-html-review';
import type { CourseArtifactJob, CourseArtifactRecord } from '@/lib/course-space';
import { COURSE_JOB_STATUS_LABELS } from '@/lib/generation/background-courseware';

const labels: Record<string, string> = {
  'course-outline': '课程教学大纲',
  'module-plan': '模块教学计划',
  'lesson-courseware': '课时 PPT / 互动课件',
  narration: '讲稿与配音',
  'exercise-set': '习题与答案',
  'assessment-rubric': '测验与评分量规',
  'pbl-project': 'PBL 项目',
};

export default function SingleCourseJobPage() {
  const { courseId, jobId } = useParams<{ courseId: string; jobId: string }>();
  const router = useRouter();
  const [job, setJob] = useState<CourseArtifactJob>();
  const [artifact, setArtifact] = useState<CourseArtifactRecord>();
  const [phase, setPhase] = useState<'generation' | 'review' | 'output'>('generation');
  const [message, setMessage] = useState('');
  const [cancelling, setCancelling] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const load = useCallback(async () => {
    try {
      const jobResponse = await fetch(`/api/course-space/jobs/${jobId}`, { cache: 'no-store' });
      const jobData = await jobResponse.json();
      if (!jobResponse.ok || jobData.success === false)
        throw new Error(jobData.error || '读取任务失败');
      const nextJob = jobData.job as CourseArtifactJob;
      setJob(nextJob);
      setMessage('');
      if (nextJob.artifactId) {
        const courseResponse = await fetch(`/api/course-space/${courseId}`, { cache: 'no-store' });
        const courseData = await courseResponse.json();
        const nextArtifact = (courseData.artifacts as CourseArtifactRecord[]).find(
          (item) => item.id === nextJob.artifactId,
        );
        if (nextArtifact) {
          setArtifact(nextArtifact);
          setPhase(
            nextArtifact.status === 'approved' || nextArtifact.status === 'published'
              ? 'output'
              : 'review',
          );
        }
      }
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : String(reason));
    }
  }, [courseId, jobId]);
  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    if (!job || !['queued', 'running'].includes(job.status)) return;
    const timer = window.setInterval(() => void load(), 1800);
    return () => window.clearInterval(timer);
  }, [job, load]);
  const cancel = async () => {
    setCancelling(true);
    try {
      const response = await fetch(`/api/course-space/jobs/${jobId}`, {
        method: 'PATCH',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ action: 'cancel' }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || '取消失败');
      setJob(data.job);
      setMessage(
        data.job.status === 'cancelled' ? '任务已取消，已完成的页面仍然保留。' : '任务已完成。',
      );
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setCancelling(false);
    }
  };
  const review = async (action: 'save' | 'approve') => {
    if (!artifact) return;
    const response = await fetch(`/api/course-space/${courseId}/artifacts/${artifact.id}`, {
      method: 'PATCH',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        action,
        content: artifact.content,
        reviewerNote: artifact.reviewerNote,
      }),
    });
    const data = await response.json();
    if (!response.ok || data.success === false) return setMessage(data.error || '审核失败');
    setArtifact(data.artifact);
    setMessage(action === 'approve' ? '审核通过，已生成可视化产物。' : '修改已保存。');
    if (action === 'approve') setPhase('output');
  };
  const retry = async () => {
    setRetrying(true);
    try {
      const response = await fetch(`/api/course-space/jobs/${jobId}`, {
        method: 'PATCH',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ action: 'retry' }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || '重试失败');
      setJob(data.job);
      setMessage('');
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setRetrying(false);
    }
  };
  const steps = [
    ['generation', '生成'],
    ['review', '审核'],
    ['output', '可视化输出'],
  ] as const;
  const current = steps.findIndex(([key]) => key === phase);
  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top,#eef3ff,transparent_45%),#f8fafc] text-slate-900">
      <header className="flex items-center gap-3 border-b bg-white/90 px-6 py-4">
        <Button
          variant="ghost"
          size="icon"
          aria-label="返回教师工作区"
          onClick={() => router.push(`/course-space?workspace=${encodeURIComponent(courseId)}`)}
        >
          <ArrowLeft />
        </Button>
        <div>
          <h1 className="text-xl font-semibold">
            {job ? labels[job.artifactType] : '教学产物生成'}
          </h1>
          <p className="text-sm text-muted-foreground">单任务生成、审核与可视化输出</p>
        </div>
      </header>
      <section className="mx-auto max-w-5xl p-6">
        <div className="mb-8 flex items-center justify-center">
          {steps.map(([key, label], index) => (
            <div key={key} className="flex items-center">
              <div
                className={`flex h-10 items-center gap-2 rounded-full px-4 text-sm font-medium ${index <= current ? 'bg-violet-600 text-white' : 'bg-white text-slate-400 ring-1 ring-slate-200'}`}
              >
                {index < current ? (
                  <Check className="size-4" />
                ) : index === current &&
                  phase === 'generation' &&
                  job?.status !== 'failed' &&
                  job?.status !== 'cancelled' ? (
                  <LoaderCircle className="size-4 animate-spin" />
                ) : (
                  <span>{index + 1}</span>
                )}
                {label}
              </div>
              {index < steps.length - 1 && (
                <div
                  className={`h-0.5 w-20 ${index < current ? 'bg-violet-600' : 'bg-slate-200'}`}
                />
              )}
            </div>
          ))}
        </div>
        {phase === 'generation' && (
          <div className="rounded-2xl border bg-white p-8 shadow-sm">
            <div className="mb-6 flex items-start justify-between">
              <div>
                <h2 className="text-2xl font-semibold">
                  {!job
                    ? '正在读取任务'
                    : job.status === 'cancelled'
                      ? '任务已取消'
                      : job?.status === 'failed'
                        ? job.backgroundGeneration?.failedPages?.length
                          ? '部分页面待重试'
                          : '生成已中断'
                        : job?.backgroundGeneration
                          ? '服务器正在生成完整课件'
                          : '正在生成单个教学产物'}
                </h2>
                <p className="mt-2 text-muted-foreground">
                  {job?.message || '正在读取已保存的进度…'}
                </p>
                {job?.backgroundGeneration && (
                  <p className="mt-2 text-sm text-muted-foreground">
                    已完成 {job.backgroundGeneration.completedPages}/
                    {job.backgroundGeneration.totalPages} 页。
                    {['queued', 'running'].includes(job.status) &&
                      '可以关闭页面或退出浏览器，回来后从“…”里的“任务记录”查看进度。'}
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
              aria-valuenow={job?.progress || 0}
            >
              <div
                className="h-full rounded-full bg-gradient-to-r from-blue-500 to-violet-600 transition-all"
                style={{ width: `${job?.progress || 0}%` }}
              />
            </div>
            <div className="mt-3 flex justify-between text-sm">
              <span>{job ? COURSE_JOB_STATUS_LABELS[job.status] : '读取中'}</span>
              <span>{job?.progress || 0}%</span>
            </div>
            {job?.error && (
              <div className="mt-5 rounded-lg bg-red-50 p-3 text-sm text-red-700">{job.error}</div>
            )}
            {!!job?.backgroundGeneration?.failedPages?.some((page) => page.issues.length) && (
              <details className="mt-3 text-sm text-muted-foreground">
                <summary className="cursor-pointer">查看校验详情</summary>
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
            {job?.backgroundGeneration && (
              <div className="mt-6 flex flex-wrap gap-3">
                {job.status === 'failed' && (
                  <Button disabled={retrying} onClick={() => void retry()}>
                    {retrying ? '正在提交重试…' : '重试未完成页面'}
                  </Button>
                )}
                {['queued', 'running'].includes(job.status) && (
                  <Button variant="outline" disabled={cancelling} onClick={() => void cancel()}>
                    {cancelling ? '正在取消…' : '取消未完成任务'}
                  </Button>
                )}
                {job.backgroundGeneration.completedPages > 0 &&
                  !['queued', 'running'].includes(job.status) && (
                    <Button
                      variant="outline"
                      onClick={() =>
                        router.push(`/classroom/${job.backgroundGeneration!.classroomId}`)
                      }
                    >
                      查看已生成页面
                    </Button>
                  )}
                <Button
                  variant="ghost"
                  onClick={() =>
                    router.push(`/course-space?workspace=${encodeURIComponent(courseId)}`)
                  }
                >
                  返回课程工作区
                </Button>
              </div>
            )}
          </div>
        )}
        {phase === 'review' && artifact && (
          <div className="space-y-4">
            {job?.backgroundGeneration && (
              <div className="flex items-center justify-between rounded-xl border bg-white p-4">
                <p className="text-sm">
                  完整课件已生成，共 {job.backgroundGeneration.completedPages} 页。
                </p>
                <Button
                  onClick={() => router.push(`/classroom/${job.backgroundGeneration!.classroomId}`)}
                >
                  打开课件并测试播放
                </Button>
              </div>
            )}
            <div>
              <h2 className="text-2xl font-semibold">审核生成内容</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                检查并修改内容，通过后直接进入可视化结果。
              </p>
            </div>
            <ArtifactHtmlReview
              artifact={artifact}
              onChange={(content) => setArtifact({ ...artifact, content })}
            />
            <div className="rounded-xl border bg-white p-4">
              <Input
                placeholder="审核说明（可选）"
                value={artifact.reviewerNote || ''}
                onChange={(e) => setArtifact({ ...artifact, reviewerNote: e.target.value })}
              />
              <div className="mt-4 flex gap-2">
                <Button variant="outline" onClick={() => void review('save')}>
                  保存修改
                </Button>
                <Button onClick={() => void review('approve')}>审核通过并生成可视化结果</Button>
              </div>
            </div>
          </div>
        )}
        {phase === 'output' && artifact && (
          <div className="space-y-4">
            <div className="flex items-end justify-between gap-4">
              <div>
                <h2 className="text-2xl font-semibold">可视化教学产物</h2>
                <p className="mt-1 text-sm text-muted-foreground">
                  审核版本已固定，可全屏查看、下载 Word 或进入课程产物库。
                </p>
              </div>
              <div className="flex gap-2">
                <Button
                  onClick={() =>
                    router.push(`/course-space/${courseId}/artifacts/${artifact.id}/view`)
                  }
                >
                  <Expand className="mr-2 size-4" />
                  全屏查看
                </Button>
                <Button
                  variant="outline"
                  onClick={() => router.push(`/course-space/${courseId}/artifacts`)}
                >
                  <Eye className="mr-2 size-4" />
                  查看全部产物
                </Button>
              </div>
            </div>
            <ArtifactHtmlReview artifact={artifact} onChange={() => {}} readOnly />
          </div>
        )}
        {message && (
          <div className="mt-4 rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm text-blue-800">
            {message}
          </div>
        )}
      </section>
    </main>
  );
}
