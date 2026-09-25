'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import {
  ArrowLeft,
  Bot,
  Check,
  ChevronRight,
  CircleAlert,
  FileCheck2,
  FileText,
  Layers3,
  LoaderCircle,
  PackageCheck,
  Presentation,
  Upload,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import type { CourseArtifactJob, CourseArtifactRecord, CourseSpace } from '@/lib/course-space';

const artifactNames: Record<string, string> = {
  'course-outline': '教学大纲',
  'module-plan': '教学计划',
  'lesson-courseware': '课件',
  narration: '讲稿',
  'exercise-set': '习题',
  'assessment-rubric': '评分量规',
  'pbl-project': 'PBL 项目',
};

export default function CourseOverviewPage() {
  const { courseId } = useParams<{ courseId: string }>();
  const router = useRouter();
  const [course, setCourse] = useState<CourseSpace>();
  const [jobs, setJobs] = useState<CourseArtifactJob[]>([]);
  const [artifacts, setArtifacts] = useState<CourseArtifactRecord[]>([]);
  const [error, setError] = useState('');
  const [materialMessage, setMaterialMessage] = useState('');
  const [materialBusy, setMaterialBusy] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [publishMessage, setPublishMessage] = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);
  const load = useCallback(async () => {
    try {
      const response = await fetch(`/api/course-space/${courseId}`, { cache: 'no-store' });
      const data = await response.json();
      if (!response.ok || data.success === false) throw new Error(data.error || '读取课程失败');
      setCourse(data.course);
      setJobs(data.jobs);
      setArtifacts(data.artifacts);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }, [courseId]);
  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    if (!course?.materials.some((item) => item.status === 'parsing')) return;
    const timer = window.setInterval(() => void load(), 2500);
    return () => window.clearInterval(timer);
  }, [course?.materials, load]);
  const uploadMaterials = async (files: File[]) => {
    if (!files.length) return;
    setMaterialBusy(true);
    setMaterialMessage('');
    try {
      for (const file of files) {
        const form = new FormData();
        form.append('file', file);
        const response = await fetch(`/api/course-space/${courseId}/materials`, {
          method: 'POST',
          body: form,
        });
        const data = await response.json();
        if (!response.ok || data.success === false)
          throw new Error(data.error || `上传 ${file.name} 失败`);
      }
      setMaterialMessage('材料已保存。请选择需要解析的文件，不会自动触发知识抽取或课件生成。');
      await load();
    } catch (reason) {
      setMaterialMessage(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setMaterialBusy(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };
  const parseMaterial = async (materialId: string) => {
    setMaterialBusy(true);
    setMaterialMessage('');
    try {
      const response = await fetch(`/api/course-space/${courseId}/materials/${materialId}/parse`, {
        method: 'POST',
      });
      const data = await response.json();
      if (!response.ok || data.success === false) throw new Error(data.error || '启动材料解析失败');
      setMaterialMessage('材料解析任务已启动，完成后可建立或更新课程知识图谱。');
      await load();
    } catch (reason) {
      setMaterialMessage(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setMaterialBusy(false);
    }
  };
  const publishCourse = async () => {
    setPublishing(true);
    setPublishMessage('');
    try {
      const response = await fetch(`/api/course-space/${courseId}/publish`, { method: 'POST' });
      const data = await response.json();
      if (!response.ok || data.success === false) throw new Error(data.error || '发布课程失败');
      setPublishMessage(
        '课程已发布到 Class 通道。只有教师确认发布并激活的生成产物会在班级资料中显示。',
      );
      await load();
    } catch (reason) {
      setPublishMessage(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setPublishing(false);
    }
  };
  const stats = useMemo(() => {
    if (!course) return undefined;
    const ready = course.materials.filter((item) => item.status === 'ready').length;
    const lessons = course.modules.reduce((sum, item) => sum + item.lessons.length, 0);
    const has = (type: string) => artifacts.some((item) => item.type === type);
    const milestones = [
      ready > 0,
      course.modules.length > 0 && lessons > 0,
      has('course-outline'),
      has('lesson-courseware'),
    ];
    return {
      ready,
      lessons,
      progress: Math.round((milestones.filter(Boolean).length / milestones.length) * 100),
      has,
    };
  }, [artifacts, course]);
  if (!course || !stats)
    return (
      <main className="flex min-h-screen items-center justify-center bg-slate-50 text-muted-foreground">
        {error || '正在读取课程状态…'}
      </main>
    );
  const latestJob = jobs[0];
  const foundationReady =
    stats.ready > 0 && stats.has('course-outline') && stats.has('lesson-courseware');
  const approvedCount = artifacts.filter((item) => item.status === 'approved').length;
  const statusItems = [
    {
      title: '课程材料',
      done: stats.ready > 0,
      detail: course.materials.length
        ? `${stats.ready}/${course.materials.length} 份已完成解析`
        : '尚未上传课程材料',
      icon: Upload,
    },
    {
      title: '课程结构',
      done: course.modules.length > 0 && stats.lessons > 0,
      detail: `${course.modules.length} 个模块 · ${stats.lessons} 个课时`,
      icon: Layers3,
    },
    {
      title: '课程教学大纲',
      done: stats.has('course-outline'),
      detail: stats.has('course-outline') ? '已生成，可进入审核或继续完善' : '建议在材料解析后生成',
      icon: FileCheck2,
    },
    {
      title: '课时 PPT / 互动课件',
      done: stats.has('lesson-courseware'),
      detail: stats.has('lesson-courseware') ? '已有课件产物' : '尚未生成，需要选择课时和来源材料',
      icon: Presentation,
    },
  ];
  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_20%_0%,rgba(59,130,246,.12),transparent_30%),radial-gradient(circle_at_85%_85%,rgba(176,0,85,.09),transparent_32%),#f7f9fc] text-slate-900">
      <header className="flex items-center justify-between border-b border-white/80 bg-white/80 px-7 py-4 backdrop-blur-xl">
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="icon"
            className="rounded-full"
            onClick={() => router.push('/course-space')}
          >
            <ArrowLeft />
          </Button>
          <img src="/brand-mark.png" alt="MENTRA" className="size-10" />
          <div>
            <h1 className="text-lg font-semibold">课程建设概览</h1>
            <p className="text-xs text-muted-foreground">先检查当前状态，再进入教师课程工作区</p>
          </div>
        </div>
        <Button variant="outline" className="rounded-full" onClick={() => router.push('/')}>
          返回首页
        </Button>
      </header>
      <section className="mx-auto max-w-7xl px-7 py-8">
        <div className="overflow-hidden rounded-[30px] bg-gradient-to-br from-slate-900 via-[#3A1830] to-[#8F0046] p-8 text-white shadow-[0_35px_90px_-45px_rgba(79,18,49,.8)]">
          <div className="flex flex-wrap items-start justify-between gap-6">
            <div>
              <span className="rounded-full bg-white/10 px-3 py-1.5 text-xs">
                {course.status === 'active' ? '已有发布知识包' : '课程建设中'}
              </span>
              <h2 className="mt-5 text-3xl font-semibold">{course.title}</h2>
              <p className="mt-2 text-sm text-white/65">
                {course.subject || '完整课程体系'} · 来源可追溯 · 教师审核后发布
              </p>
            </div>
            <div className="min-w-64 rounded-2xl bg-white/10 p-5">
              <div className="flex justify-between text-sm">
                <span>课程建设进度</span>
                <b>{stats.progress}%</b>
              </div>
              <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/15">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-pink-300 to-white"
                  style={{ width: `${stats.progress}%` }}
                />
              </div>
              <p className="mt-3 text-xs text-white/60">按材料、结构、大纲和课件四个关键节点计算</p>
            </div>
          </div>
        </div>
        <div className="mt-6 grid gap-5 lg:grid-cols-[1fr_360px]">
          <div className="rounded-[26px] border border-white/80 bg-white/90 p-6 shadow-sm">
            <div className="flex items-center justify-between gap-4">
              <div>
                <h3 className="text-xl font-semibold">当前课程状态</h3>
                <p className="mt-1 text-sm text-muted-foreground">
                  系统根据真实材料、结构和已生成产物给出下一步。
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <Button
                  className="rounded-xl bg-[#B00055] hover:bg-[#8F0046]"
                  onClick={() => router.push(`/course-space?workspace=${course.id}`)}
                >
                  <Bot className="mr-2 size-4" />
                  进入教师工作区
                </Button>
                <Button
                  className="rounded-xl bg-[#B00055] hover:bg-[#8F0046]"
                  disabled={publishing || approvedCount === 0}
                  onClick={() => void publishCourse()}
                >
                  {publishing ? (
                    <LoaderCircle className="mr-2 size-4 animate-spin" />
                  ) : (
                    <PackageCheck className="mr-2 size-4" />
                  )}
                  {course.status === 'active'
                    ? approvedCount > 0
                      ? '更新发布'
                      : '已发布课程'
                    : '发布课程'}
                </Button>
              </div>
            </div>
            {publishMessage && (
              <p className="mt-4 rounded-xl bg-blue-50 px-3 py-2 text-xs text-blue-800">
                {publishMessage}
              </p>
            )}
            <div className="mt-6 grid gap-3 sm:grid-cols-2">
              {statusItems.map((item) => (
                <div
                  key={item.title}
                  className={`rounded-2xl border p-4 ${item.done ? 'border-emerald-100 bg-emerald-50/55' : 'border-amber-100 bg-amber-50/55'}`}
                >
                  <div className="flex items-start gap-3">
                    <div
                      className={`rounded-xl p-2 ${item.done ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'}`}
                    >
                      <item.icon className="size-5" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between">
                        <b>{item.title}</b>
                        {item.done ? (
                          <Check className="size-4 text-emerald-600" />
                        ) : (
                          <CircleAlert className="size-4 text-amber-600" />
                        )}
                      </div>
                      <p className="mt-1 text-xs leading-5 text-muted-foreground">{item.detail}</p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
          <aside className="space-y-5">
            <div className="rounded-[26px] border border-white/80 bg-white/90 p-5 shadow-sm">
              <h3 className="font-semibold">下一步建议</h3>
              <div className="mt-4 space-y-3 text-sm">
                {stats.ready === 0 && (
                  <button
                    onClick={() => router.push(`/course-space?workspace=${course.id}`)}
                    className="flex w-full items-center justify-between rounded-xl bg-blue-50 p-3 text-left text-blue-800"
                  >
                    <span>上传并解析课程材料</span>
                    <ChevronRight className="size-4" />
                  </button>
                )}
                {!stats.has('course-outline') && (
                  <button
                    onClick={() => router.push(`/course-space?workspace=${course.id}`)}
                    className="flex w-full items-center justify-between rounded-xl bg-[#B00055]/5 p-3 text-left text-[#8F0046]"
                  >
                    <span>生成课程教学大纲</span>
                    <ChevronRight className="size-4" />
                  </button>
                )}
                {!stats.has('lesson-courseware') && (
                  <button
                    onClick={() => router.push(`/course-space?workspace=${course.id}`)}
                    className="flex w-full items-center justify-between rounded-xl bg-orange-50 p-3 text-left text-orange-800"
                  >
                    <span>选择课时并生成课件</span>
                    <ChevronRight className="size-4" />
                  </button>
                )}
                {foundationReady && (
                  <button
                    onClick={() => router.push(`/course-space?workspace=${course.id}`)}
                    className="flex w-full items-center justify-between rounded-xl bg-emerald-50 p-3 text-left text-emerald-800"
                  >
                    <span>
                      <b className="block">课程基础已就绪</b>
                      <span className="mt-1 block text-xs text-emerald-700/75">
                        进入工作区继续生成、审核或维护教学产物
                      </span>
                    </span>
                    <ChevronRight className="size-4 shrink-0" />
                  </button>
                )}
              </div>
            </div>
            <div className="rounded-[26px] border border-white/80 bg-white/90 p-5 shadow-sm">
              <div className="flex items-center gap-2">
                <PackageCheck className="size-5 text-[#B00055]" />
                <h3 className="font-semibold">教学产物</h3>
              </div>
              <div className="mt-4 flex items-end justify-between">
                <div>
                  <b className="text-3xl">{artifacts.length}</b>
                  <p className="text-xs text-muted-foreground">个已生成产物</p>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!artifacts.length}
                  onClick={() => router.push(`/course-space/${course.id}/artifacts`)}
                >
                  查看产物
                </Button>
              </div>
              {latestJob && (
                <button
                  onClick={() => router.push(`/course-space/${course.id}/jobs/${latestJob.id}`)}
                  className="mt-4 flex w-full items-center justify-between rounded-xl bg-slate-50 p-3 text-left text-xs"
                >
                  <span className="truncate">
                    <FileText className="mr-2 inline size-3" />
                    {artifactNames[latestJob.artifactType] || latestJob.artifactType}
                  </span>
                  <span>
                    {latestJob.status} · {latestJob.progress}%
                  </span>
                </button>
              )}
            </div>
          </aside>
        </div>
        <div className="mt-6">
          <section className="rounded-[26px] border border-white/80 bg-white/90 p-5 shadow-sm">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="flex items-center gap-2">
                  <Upload className="size-5 text-blue-600" />
                  <h3 className="font-semibold">课程资料</h3>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  集中上传、查看并手动解析课程原始材料。
                </p>
              </div>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                className="hidden"
                onChange={(event) => void uploadMaterials(Array.from(event.target.files ?? []))}
              />
              <Button
                variant="outline"
                className="rounded-xl"
                disabled={materialBusy}
                onClick={() => fileInputRef.current?.click()}
              >
                {materialBusy && <LoaderCircle className="mr-2 size-4 animate-spin" />}上传材料
              </Button>
            </div>
            {materialMessage && (
              <p className="mt-4 rounded-xl bg-blue-50 px-3 py-2 text-xs text-blue-800">
                {materialMessage}
              </p>
            )}
            <div className="mt-4 grid max-h-[560px] gap-3 overflow-y-auto pr-1 sm:grid-cols-2">
              {course.materials.length ? (
                course.materials.map((item) => (
                  <div key={item.id} className="rounded-2xl border bg-slate-50/75 p-3">
                    <div className="flex items-center gap-2">
                      <FileText className="size-4 shrink-0 text-slate-500" />
                      <span className="min-w-0 flex-1 truncate text-sm font-medium">
                        {item.name}
                      </span>
                      <span
                        className={`rounded-full px-2 py-0.5 text-[10px] ${item.status === 'ready' ? 'bg-emerald-100 text-emerald-700' : item.status === 'failed' ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'}`}
                      >
                        {item.status}
                      </span>
                    </div>
                    <p className="mt-2 text-[11px] text-muted-foreground">
                      {item.pageCount
                        ? `${item.pageCount} 页 · ${item.parser}`
                        : `${Math.max(1, Math.round(item.size / 1024))} KB`}
                    </p>
                    {item.error && (
                      <p className="mt-2 line-clamp-2 text-[11px] text-red-600">{item.error}</p>
                    )}
                    {['uploaded', 'failed'].includes(item.status) && (
                      <Button
                        size="sm"
                        variant="outline"
                        className="mt-3 h-8 rounded-lg bg-white text-xs"
                        disabled={materialBusy}
                        onClick={() => void parseMaterial(item.id)}
                      >
                        解析材料
                      </Button>
                    )}
                  </div>
                ))
              ) : (
                <div className="col-span-full rounded-2xl border border-dashed p-8 text-center text-sm text-muted-foreground">
                  尚未上传课程资料
                </div>
              )}
            </div>
          </section>
        </div>
      </section>
    </main>
  );
}
