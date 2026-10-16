'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import {
  ArrowLeft,
  Check,
  FileText,
  FolderOpen,
  LoaderCircle,
  Sparkles,
  Upload,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { ResourceActions } from '@/components/course-space/resource-actions';
import {
  ResourcePublicationDialog,
  type PublicationTarget,
} from '@/components/course-space/resource-publication-dialog';
import type { CourseArtifactJob, CourseArtifactRecord, CourseSpace } from '@/lib/course-space';
import type { CourseScheduleInput } from '@/lib/server/course-onboarding';
const steps = ['上传并解析课程资料', '完成并审核课程大纲', '完善课程信息与安排'];
async function readResponse(response: Response) {
  const body = await response.json();
  if (!response.ok || body.success === false) throw new Error(body.error || '操作失败，请重试');
  return body;
}
export default function CourseOnboardingPage() {
  const { courseId } = useParams<{ courseId: string }>();
  const router = useRouter();
  const [course, setCourse] = useState<CourseSpace>();
  const [publicationTarget, setPublicationTarget] = useState<PublicationTarget>();
  const [artifacts, setArtifacts] = useState<CourseArtifactRecord[]>([]);
  const [jobs, setJobs] = useState<CourseArtifactJob[]>([]);
  const [step, setStep] = useState(1);
  const [outlineId, setOutlineId] = useState('');
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const initialized = useRef('');
  const generatingJobId = useRef('');
  const materialInput = useRef<HTMLInputElement>(null);
  const outlineInput = useRef<HTMLInputElement>(null);
  const [schedule, setSchedule] = useState<CourseScheduleInput>({
    title: '',
    subject: '',
    gradeBand: '',
    term: '',
    description: '',
    totalWeeks: 16,
    lessonsPerWeek: 1,
    teachingHoursPerLesson: 2,
    hasLab: false,
  });
  const load = useCallback(async () => {
    const data = await readResponse(
      await fetch(`/api/course-space/${courseId}`, { cache: 'no-store' }),
    );
    const next = data.course as CourseSpace;
    if (next.onboarding?.completedAt || (!next.onboarding && next.modules.length > 0)) {
      router.replace(`/course-space?workspace=${encodeURIComponent(next.id)}`);
      return;
    }
    setCourse(next);
    setArtifacts(data.artifacts);
    setJobs(data.jobs);
    if (initialized.current !== courseId) {
      initialized.current = courseId;
      setStep(next.onboarding?.step ?? 1);
      setSchedule({
        title: next.title,
        subject: next.subject ?? '',
        gradeBand: next.gradeBand ?? '',
        term: next.term ?? '',
        description: next.description ?? '',
        totalWeeks: next.curriculum?.totalWeeks ?? 16,
        lessonsPerWeek: next.curriculum?.lessonsPerWeek ?? 1,
        teachingHoursPerLesson: next.curriculum?.teachingHoursPerLesson ?? 2,
        hasLab: next.curriculum?.hasLab ?? false,
      });
    }
    const generated = data.jobs.find(
      (item: CourseArtifactJob) => item.id === generatingJobId.current && item.artifactId,
    )?.artifactId;
    setOutlineId(
      (current) =>
        generated ||
        (data.artifacts.some((item: CourseArtifactRecord) => item.id === current)
          ? current
          : next.onboarding?.outlineArtifactId ||
            [...data.artifacts]
              .filter((item: CourseArtifactRecord) => item.type === 'course-outline')
              .sort((a, b) => b.createdAt - a.createdAt)[0]?.id ||
            ''),
    );
  }, [courseId, router]);
  useEffect(() => {
    void load().catch((error) => setError(error.message));
    const timer = window.setInterval(
      () => void load().catch((error) => setError(error.message)),
      2500,
    );
    return () => window.clearInterval(timer);
  }, [load]);
  const outline = artifacts.find((item) => item.id === outlineId);
  useEffect(() => {
    setDraft(outline?.content ?? '');
  }, [outline?.id, outline?.content]);
  const sources = course?.materials.filter((item) => item.purpose !== 'course-outline') ?? [];
  const uploadedOutlines =
    course?.materials.filter((item) => item.purpose === 'course-outline') ?? [];
  const sourceReady = sources.length > 0 && sources.every((item) => item.status === 'ready');
  const activeJob = jobs.find(
    (item) => item.artifactType === 'course-outline' && ['queued', 'running'].includes(item.status),
  );
  const latestJob = [...jobs]
    .filter((item) => item.artifactType === 'course-outline')
    .sort((a, b) => b.createdAt - a.createdAt)[0];
  const run = async (action: () => Promise<void>) => {
    if (busy) return;
    setBusy(true);
    setError('');
    setMessage('');
    try {
      await action();
    } catch (error) {
      setError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
      await load().catch(() => undefined);
    }
  };
  const parse = async (id: string) => {
    await readResponse(
      await fetch(`/api/course-space/${courseId}/materials/${id}/parse`, { method: 'POST' }),
    );
  };
  const upload = async (files: File[], purpose: 'course-material' | 'course-outline') => {
    await run(async () => {
      for (const file of files) {
        if (file.size > 80 * 1024 * 1024) throw new Error(`${file.name} 超过80MB`);
        const form = new FormData();
        form.append('file', file);
        form.append('purpose', purpose);
        const result = await readResponse(
          await fetch(`/api/course-space/${courseId}/materials`, { method: 'POST', body: form }),
        );
        await parse(result.material.id);
      }
      setMessage(
        purpose === 'course-outline'
          ? '大纲已上传并开始解析。解析完成后，点击“载入大纲审核”。'
          : '资料已保存并开始解析，完成后可继续下一步。',
      );
    });
    if (materialInput.current) materialInput.current.value = '';
    if (outlineInput.current) outlineInput.current.value = '';
  };
  const setup = async (body: object) =>
    readResponse(
      await fetch(`/api/course-space/${courseId}/setup`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
      }),
    );
  const generateOutline = () =>
    run(async () => {
      const data = await readResponse(
        await fetch(`/api/course-space/${courseId}/jobs`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ scope: { type: 'course' }, artifactTypes: ['course-outline'] }),
        }),
      );
      generatingJobId.current = data.jobs[0].id;
      setMessage('已启动现有大纲生成流程。完成后请逐段审阅、修改并确认。');
    });
  const saveOutline = (approve: boolean) =>
    run(async () => {
      if (!outline) return;
      await readResponse(
        await fetch(`/api/course-space/${courseId}/artifacts/${outline.id}`, {
          method: 'PATCH',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ action: approve ? 'approve' : 'save', content: draft }),
        }),
      );
      if (approve) {
        await setup({ action: 'advance', step: 3, outlineArtifactId: outline.id });
        setStep(3);
      } else setMessage('大纲修改已保存，尚未审核通过。');
    });
  const complete = () =>
    run(async () => {
      const data = await setup({ action: 'complete', outlineArtifactId: outlineId, schedule });
      router.replace(`/course-space?workspace=${encodeURIComponent(data.course.id)}`);
    });
  if (!course)
    return (
      <main className="grid min-h-screen place-items-center bg-slate-50">
        <p>{error || '正在打开建课引导…'}</p>
      </main>
    );
  const inputClass =
    'mt-1.5 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none focus:border-[#B00055]';
  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top_left,#fff2f8,transparent_45%),#f8fafc] pb-12 text-slate-900">
      <header className="flex items-center gap-3 border-b bg-white/90 px-6 py-4">
        <Button
          variant="ghost"
          size="icon"
          aria-label="返回课程中心"
          onClick={() => router.push('/course-space')}
        >
          <ArrowLeft />
        </Button>
        <img src="/brand-mark.png" alt="" className="size-10" />
        <div>
          <h1 className="text-xl font-semibold">新课程准备</h1>
          <p className="mt-1 text-xs text-slate-500">
            {course.title} · 上传资料、审核大纲、安排课程
          </p>
        </div>
        <span className="ml-auto text-xs text-slate-500">资料与审核进度自动保留</span>
      </header>
      <div className="mx-auto max-w-5xl px-5 pt-8">
        <nav aria-label="建课步骤" className="mb-6 grid gap-3 sm:grid-cols-3">
          {steps.map((title, index) => (
            <button
              key={title}
              disabled={busy || index + 1 > (course.onboarding?.step ?? 1)}
              onClick={() => setStep(index + 1)}
              className={`flex items-center gap-3 rounded-2xl border p-4 text-left ${step === index + 1 ? 'border-[#B00055]/30 bg-[#B00055]/5' : 'border-slate-200 bg-white'}`}
            >
              <span
                className={`grid size-8 shrink-0 place-items-center rounded-full ${step === index + 1 ? 'bg-[#B00055] text-white' : 'bg-slate-100 text-slate-500'}`}
              >
                {(course.onboarding?.step ?? 1) > index + 1 ? (
                  <Check className="size-4" />
                ) : (
                  index + 1
                )}
              </span>
              <span className="text-sm font-medium">{title}</span>
            </button>
          ))}
        </nav>
        <section className="rounded-3xl border bg-white p-6 shadow-sm sm:p-8">
          <p className="text-xs font-medium text-[#B00055]">第 {step} 步 / 共 3 步</p>
          <h2 className="mt-2 text-2xl font-semibold">{steps[step - 1]}</h2>
          {step === 1 && (
            <div className="mt-5 space-y-5">
              <p className="text-sm leading-6 text-slate-500">
                上传教材、讲义、参考资料或已有课件。原始文件将归入工作区的“课程资料”，解析文本、页码与来源引用保存在课程数据库中，供后续大纲和课件使用。
              </p>
              <input
                ref={materialInput}
                type="file"
                multiple
                accept=".pdf,.ppt,.pptx,.doc,.docx,.txt,.md"
                className="hidden"
                onChange={(event) =>
                  void upload(Array.from(event.target.files ?? []), 'course-material')
                }
              />
              <div className="rounded-2xl border border-dashed border-[#B00055]/30 bg-[#fff8fb] p-6 text-center">
                <Upload className="mx-auto mb-3 size-7 text-[#B00055]" />
                <Button disabled={busy} onClick={() => materialInput.current?.click()}>
                  上传并解析课程资料
                </Button>
                <p className="mt-3 text-xs text-slate-500">
                  支持 PDF、Word、PPT、TXT、Markdown，可多选；每个文件最大80MB。
                </p>
              </div>
              <div className="space-y-2">
                {sources.map((item) => (
                  <div key={item.id} className="flex items-center gap-3 rounded-xl border p-3">
                    <FileText className="size-4 shrink-0 text-[#B00055]" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{item.name}</p>
                      <p className="mt-1 text-xs text-slate-500">
                        {item.status === 'ready'
                          ? `已解析 · ${item.pageCount ?? 0} 页`
                          : item.status === 'parsing'
                            ? '正在解析…'
                            : item.status === 'failed'
                              ? `解析失败：${item.error || '请重试'}`
                              : '等待解析'}
                      </p>
                    </div>
                    {!['ready', 'parsing'].includes(item.status) && (
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={busy}
                        onClick={() => void run(() => parse(item.id))}
                      >
                        {item.status === 'failed' ? '重试解析' : '开始解析'}
                      </Button>
                    )}
                    <ResourceActions
                      courseId={course.id}
                      course={course}
                      kind="materials"
                      id={item.id}
                      title={item.name}
                      published={Boolean(item.classPublicationId)}
                      courseActive={course.status === 'active'}
                      onChange={load}
                      onPublish={() =>
                        setPublicationTarget({
                          kind: 'material',
                          id: item.id,
                          title: item.name,
                          resourceType: 'material',
                          storageType: item.mimeType,
                          lessonId: item.publicationPlacement?.lessonId,
                        })
                      }
                    />
                  </div>
                ))}
              </div>
              <div className="flex items-center justify-between border-t pt-5">
                <p className="text-xs text-slate-500">
                  已解析 {sources.filter((item) => item.status === 'ready').length} /{' '}
                  {sources.length} 份资料
                </p>
                <Button
                  disabled={busy || !sourceReady}
                  onClick={() =>
                    void run(async () => {
                      await setup({ action: 'advance', step: 2 });
                      setStep(2);
                    })
                  }
                >
                  下一步：课程大纲
                </Button>
              </div>
            </div>
          )}
          {step === 2 && (
            <div className="mt-5 space-y-5">
              <p className="text-sm leading-6 text-slate-500">
                选择上传自己的大纲，或基于第一步资料使用 AI
                生成。两种方式都需教师审阅修改并审核通过；审核后的文档将保存在“课程大纲”文件夹。
              </p>
              <input
                ref={outlineInput}
                type="file"
                accept=".pdf,.doc,.docx,.txt,.md"
                className="hidden"
                onChange={(event) =>
                  void upload(Array.from(event.target.files ?? []), 'course-outline')
                }
              />
              <div className="grid gap-3 sm:grid-cols-2">
                <Button
                  variant="outline"
                  disabled={busy || Boolean(activeJob)}
                  onClick={() => outlineInput.current?.click()}
                >
                  <Upload className="mr-2 size-4" />
                  上传已有课程大纲
                </Button>
                <Button
                  disabled={busy || !sourceReady || Boolean(activeJob)}
                  onClick={() => void generateOutline()}
                >
                  <Sparkles className="mr-2 size-4" />
                  {activeJob ? '大纲正在生成…' : 'AI辅助生成新大纲'}
                </Button>
              </div>
              {uploadedOutlines.map((item) => (
                <div
                  key={item.id}
                  className="flex items-center justify-between gap-3 rounded-xl border p-3"
                >
                  <span className="min-w-0 truncate text-sm">
                    {item.name} ·{' '}
                    {item.status === 'ready'
                      ? '已解析'
                      : item.status === 'failed'
                        ? '解析失败'
                        : '解析中'}
                  </span>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={busy || item.status === 'parsing'}
                    onClick={() =>
                      void run(async () => {
                        if (item.status !== 'ready') {
                          await parse(item.id);
                          return;
                        }
                        const data = await setup({ action: 'import-outline', materialId: item.id });
                        generatingJobId.current = '';
                        await load();
                        setOutlineId(data.artifact.id);
                      })
                    }
                  >
                    {item.status === 'ready' ? '载入大纲审核' : '重试解析'}
                  </Button>
                </div>
              ))}
              {activeJob && (
                <div role="status" className="rounded-xl bg-[#fff8fb] p-4 text-sm text-[#B00055]">
                  <LoaderCircle className="mr-2 inline size-4 animate-spin" />
                  {activeJob.message} · {activeJob.progress}%
                </div>
              )}
              {latestJob?.status === 'failed' && (
                <p role="alert" className="text-sm text-red-600">
                  大纲生成失败：{latestJob.error || latestJob.message}。可重试生成或上传自己的大纲。
                </p>
              )}
              {outline && (
                <div className="space-y-3">
                  <label className="block text-sm font-medium">
                    审核大纲版本
                    <select
                      value={outlineId}
                      onChange={(event) => {
                        generatingJobId.current = '';
                        setOutlineId(event.target.value);
                      }}
                      className={inputClass}
                    >
                      {artifacts
                        .filter((item) => item.type === 'course-outline')
                        .map((item) => (
                          <option key={item.id} value={item.id}>
                            {item.title} ·{' '}
                            {item.status === 'approved' || item.status === 'published'
                              ? '已审核'
                              : '待审核'}
                          </option>
                        ))}
                    </select>
                  </label>
                  <p className="text-xs text-slate-500">
                    请核对课程目标、教学内容、重点难点、评价方式和课时安排。可直接修改下方内容。
                  </p>
                  <textarea
                    aria-label="审核并修改课程大纲"
                    value={draft}
                    onChange={(event) => setDraft(event.target.value)}
                    readOnly={outline.status === 'published'}
                    className="h-[420px] w-full resize-y rounded-xl border p-4 font-mono text-sm leading-7 outline-none focus:border-[#B00055]"
                  />
                  <Button
                    variant="outline"
                    disabled={busy || !draft.trim() || outline.status === 'published'}
                    onClick={() => void saveOutline(false)}
                  >
                    保存大纲修改
                  </Button>
                </div>
              )}
              {!outline && !activeJob && (
                <p className="rounded-xl bg-slate-50 p-5 text-sm text-slate-500">
                  尚无大纲。请先选择上方一种方式，完成后会在这里进入审核。
                </p>
              )}
              <div className="flex justify-between border-t pt-5">
                <Button variant="outline" disabled={busy} onClick={() => setStep(1)}>
                  上一步
                </Button>
                <Button
                  disabled={busy || !outline || !draft.trim() || Boolean(activeJob)}
                  onClick={() =>
                    outline?.status === 'published'
                      ? void run(async () => {
                          await setup({
                            action: 'advance',
                            step: 3,
                            outlineArtifactId: outline.id,
                          });
                          setStep(3);
                        })
                      : void saveOutline(true)
                  }
                >
                  审核通过并下一步
                </Button>
              </div>
            </div>
          )}
          {step === 3 && (
            <form
              className="mt-5 space-y-5"
              onSubmit={(event) => {
                event.preventDefault();
                void complete();
              }}
            >
              <p className="text-sm leading-6 text-slate-500">
                确认课程信息后，系统会按周次和每周课次创建文件夹。课程目标、知识点及课件可归入具体课次；创建目录不会自动生成或发布课件。
              </p>
              <div className="grid gap-4 sm:grid-cols-2">
                {(
                  [
                    { key: 'title', label: '课程名称', required: true },
                    { key: 'subject', label: '所属学科' },
                    { key: 'gradeBand', label: '授课对象 / 年级' },
                    { key: 'term', label: '开课学期' },
                  ] as const
                ).map((field) => (
                  <label key={field.key} className="text-sm">
                    {field.label}
                    <input
                      required={'required' in field && field.required}
                      maxLength={200}
                      value={schedule[field.key]}
                      onChange={(event) =>
                        setSchedule({ ...schedule, [field.key]: event.target.value })
                      }
                      className={inputClass}
                    />
                  </label>
                ))}
              </div>
              <label className="block text-sm">
                课程简介
                <textarea
                  value={schedule.description}
                  maxLength={2000}
                  onChange={(event) =>
                    setSchedule({ ...schedule, description: event.target.value })
                  }
                  className={inputClass}
                  rows={3}
                />
              </label>
              <div className="grid gap-4 sm:grid-cols-3">
                {(
                  [
                    { key: 'totalWeeks', label: '上课周数', max: 52, min: 1, step: 1 },
                    { key: 'lessonsPerWeek', label: '每周上课次数', max: 10, min: 1, step: 1 },
                    {
                      key: 'teachingHoursPerLesson',
                      label: '每次课时数',
                      max: 8,
                      min: 0.5,
                      step: 0.5,
                    },
                  ] as const
                ).map((field) => (
                  <label key={field.key} className="text-sm">
                    {field.label}
                    <input
                      type="number"
                      required
                      min={field.min}
                      max={field.max}
                      step={field.step}
                      value={schedule[field.key]}
                      onChange={(event) =>
                        setSchedule({ ...schedule, [field.key]: Number(event.target.value) })
                      }
                      className={inputClass}
                    />
                  </label>
                ))}
              </div>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={schedule.hasLab}
                  onChange={(event) => setSchedule({ ...schedule, hasLab: event.target.checked })}
                />
                这门课程包含实验课，创建独立的“课程实验”文件夹
              </label>
              <div className="rounded-2xl border border-[#B00055]/15 bg-[#fff8fb] p-4 text-sm leading-7">
                <p className="flex items-center gap-2 font-medium text-[#B00055]">
                  <FolderOpen className="size-4" />
                  即将建立的课程目录
                </p>
                <p>课程资料：保留第一步上传的 {sources.length} 份文件及解析结果</p>
                <p>课程大纲：保留已审核的大纲</p>
                <p>
                  AI课件：第1–{schedule.totalWeeks}周，每周{schedule.lessonsPerWeek}次课，共
                  {schedule.totalWeeks * schedule.lessonsPerWeek}个课次，每次
                  {schedule.teachingHoursPerLesson}课时
                </p>
                {schedule.hasLab && <p>课程实验：独立文件夹，可继续添加实验安排和资料</p>}
              </div>
              <div className="flex justify-between border-t pt-5">
                <Button type="button" variant="outline" disabled={busy} onClick={() => setStep(2)}>
                  上一步
                </Button>
                <Button type="submit" disabled={busy}>
                  {busy ? (
                    <LoaderCircle className="mr-2 size-4 animate-spin" />
                  ) : (
                    <Check className="mr-2 size-4" />
                  )}
                  创建目录并进入工作区
                </Button>
              </div>
            </form>
          )}
          {message && (
            <p role="status" className="mt-5 rounded-xl bg-emerald-50 p-3 text-sm text-emerald-800">
              {message}
            </p>
          )}
          {error && (
            <p role="alert" className="mt-5 rounded-xl bg-red-50 p-3 text-sm text-red-700">
              {error}
            </p>
          )}
        </section>
      </div>
      {publicationTarget && course && (
        <ResourcePublicationDialog
          course={course}
          target={publicationTarget}
          onClose={() => setPublicationTarget(undefined)}
          onPublished={load}
        />
      )}
    </main>
  );
}
