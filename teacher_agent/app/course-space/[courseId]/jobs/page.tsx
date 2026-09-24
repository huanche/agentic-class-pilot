'use client';

import { useCallback, useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { ArrowLeft, ArrowRight, CheckCircle2, Clock3, LoaderCircle, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import type { CourseArtifactJob, CourseArtifactRecord, CourseSpace } from '@/lib/course-space';

const labels: Record<string, string> = {
  'course-outline': '课程教学大纲',
  'module-plan': '模块教学计划',
  'lesson-courseware': '课时 PPT / 互动课件',
  narration: '讲稿与配音',
  'exercise-set': '习题与答案',
  'assessment-rubric': '测验与评分量规',
  'pbl-project': 'PBL 项目',
};

export default function CourseJobsPage() {
  const { courseId } = useParams<{ courseId: string }>();
  const router = useRouter();
  const [course, setCourse] = useState<CourseSpace>();
  const [jobs, setJobs] = useState<CourseArtifactJob[]>([]);
  const [artifacts, setArtifacts] = useState<CourseArtifactRecord[]>([]);
  const [error, setError] = useState('');
  const refresh = useCallback(async () => {
    try {
      const response = await fetch(`/api/course-space/${courseId}`, { cache: 'no-store' });
      const data = await response.json();
      if (!response.ok || data.success === false) throw new Error(data.error || '读取任务失败');
      setCourse(data.course);
      setJobs(data.jobs);
      setArtifacts(data.artifacts);
      setError('');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }, [courseId]);
  useEffect(() => {
    void refresh();
  }, [refresh]);
  useEffect(() => {
    if (!jobs.some((job) => job.status === 'queued' || job.status === 'running')) return;
    const timer = window.setInterval(() => void refresh(), 2000);
    return () => window.clearInterval(timer);
  }, [jobs, refresh]);

  const completed = jobs.filter(
    (job) => job.status === 'review' || job.status === 'approved',
  ).length;
  return (
    <main className="min-h-screen bg-slate-50 text-slate-900">
      <header className="flex items-center justify-between border-b bg-white px-6 py-4">
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="icon"
            aria-label="返回课程建设概览"
            onClick={() => router.push(`/course-space/${courseId}`)}
          >
            <ArrowLeft />
          </Button>
          <div>
            <h1 className="text-xl font-semibold">生成任务与审核</h1>
            <p className="text-sm text-muted-foreground">
              {course?.title || '课程'} · 生成进度、结果检查与审核入口
            </p>
          </div>
        </div>
        <Button variant="outline" onClick={() => void refresh()}>
          <RefreshCw className="mr-2 size-4" />
          刷新
        </Button>
      </header>
      <section className="mx-auto max-w-5xl space-y-6 p-6">
        <div className="grid grid-cols-2 gap-4">
          <div className="rounded-xl border bg-white p-5">
            <Clock3 className="mb-2 text-blue-500" />
            <div className="text-2xl font-semibold">{jobs.length}</div>
            <div className="text-sm text-muted-foreground">当前批次及历史任务</div>
          </div>
          <div className="rounded-xl border bg-white p-5">
            <CheckCircle2 className="mb-2 text-emerald-500" />
            <div className="text-2xl font-semibold">{completed}</div>
            <div className="text-sm text-muted-foreground">已完成生成</div>
          </div>
        </div>
        <div className="rounded-xl border bg-white p-5">
          <h2 className="font-semibold">任务进度</h2>
          <div className="mt-4 space-y-3">
            {jobs.length === 0 && <p className="text-sm text-muted-foreground">暂无生成任务。</p>}
            {jobs.map((job) => (
              <div key={job.id} className="rounded-lg border p-4">
                <div className="flex items-center justify-between">
                  <b>{labels[job.artifactType] || job.artifactType}</b>
                  <span className="text-sm">
                    {job.status} · {job.progress}%
                  </span>
                </div>
                <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-100">
                  <div
                    className="h-full rounded-full bg-violet-600 transition-all"
                    style={{ width: `${job.progress}%` }}
                  />
                </div>
                <p className="mt-2 text-xs text-muted-foreground">{job.message}</p>
                {job.status === 'running' && (
                  <LoaderCircle className="mt-2 size-4 animate-spin text-violet-600" />
                )}
                {job.error && <p className="mt-2 text-xs text-red-600">{job.error}</p>}
              </div>
            ))}
          </div>
        </div>
        <div className="flex items-center justify-between rounded-xl border bg-white p-5">
          <div>
            <h2 className="font-semibold">生成完成后查看产物</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              下一页集中展示 HTML、Word 与互动课件，并提供逐产物审核入口。
            </p>
          </div>
          <Button
            disabled={artifacts.length === 0}
            onClick={() => router.push(`/course-space/${courseId}/artifacts`)}
          >
            下一步：查看生成产物
            <ArrowRight className="ml-2 size-4" />
          </Button>
        </div>
        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            {error}
          </div>
        )}
      </section>
    </main>
  );
}
