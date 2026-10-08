'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import type { TeacherOperationPlan } from '@/lib/course-space/teacher-agent-intent';
import type { CourseLessonFileType } from '@/lib/course-space/types';

type Draft = { type: CourseLessonFileType; title: string; content: string };
type LessonDraft = { lessonId: string; lessonTitle: string; baseVersion: string; drafts: Draft[] };
type Phase = 'confirm' | 'generating' | 'review' | 'saving' | 'saved';

export default function TeacherPreparationPage() {
  const { courseId } = useParams<{ courseId: string }>();
  const router = useRouter();
  const [plan, setPlan] = useState<TeacherOperationPlan | null>(null);
  const [phase, setPhase] = useState<Phase>('confirm');
  const [lessons, setLessons] = useState<LessonDraft[]>([]);
  const [failures, setFailures] = useState<Record<string, string>>({});
  const [progress, setProgress] = useState('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    try {
      const draftId = new URLSearchParams(window.location.search).get('draft');
      if (!draftId) throw new Error('缺少备课任务标识，请返回工作台重新提交命令。');
      const raw = sessionStorage.getItem(`teacher-plan:${draftId}`);
      if (!raw) throw new Error('备课计划已失效，请返回工作台重新提交命令。');
      const parsed = JSON.parse(raw) as TeacherOperationPlan;
      if (parsed.id !== draftId || parsed.action?.type !== 'create-lesson-files' ||
          !Array.isArray(parsed.action.lessonIds) || !parsed.action.lessonIds.length ||
          parsed.action.lessonIds.length > 100 ||
          parsed.action.lessonIds.some((id) => typeof id !== 'string' || !id) ||
          new Set(parsed.action.lessonIds).size !== parsed.action.lessonIds.length ||
          !parsed.action.populateContent) throw new Error('该命令不能在课时内容审核页执行');
      setPlan(parsed);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '备课计划无效');
    }
  }, []);

  const action = plan?.action?.type === 'create-lesson-files' ? plan.action : null;
  const busy = phase === 'generating' || phase === 'saving';
  const canSave = Boolean(action && lessons.length === action.lessonIds.length &&
    Object.keys(failures).length === 0 && lessons.every((lesson) =>
      lesson.drafts.length === action.fileTypes.length &&
      lesson.drafts.every((draft) => draft.content.trim() && draft.content.length <= 30000)));
  const endpoint = `/api/course-space/${encodeURIComponent(courseId)}/lesson-files/draft`;

  const generate = async (retryFailed = false) => {
    if (!action || busy) return;
    setPhase('generating');
    setError(null);
    // Retrying a failed lesson preserves successful drafts and teacher edits.
    const generated = retryFailed ? [...lessons] : [];
    const errors: Record<string, string> = {};
    const targets = retryFailed
      ? action.lessonIds.filter((id) => !generated.some((lesson) => lesson.lessonId === id))
      : action.lessonIds;
    setLessons(generated);
    setFailures({});
    for (const [index, lessonId] of targets.entries()) {
      setProgress(`正在生成第 ${index + 1}/${targets.length} 个课时；审核通过前不会覆盖原文件。`);
      try {
        const response = await fetch(endpoint, {
          method: 'POST', headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ lessonId, fileTypes: action.fileTypes, instruction: action.instruction }),
          signal: AbortSignal.timeout(120000),
        });
        const data = await response.json();
        if (!response.ok || data.success === false) throw new Error(data.error || '生成失败');
        generated.push({ lessonId, lessonTitle: data.lessonTitle, drafts: data.drafts, baseVersion: data.baseVersion });
        setLessons([...generated]);
      } catch (caught) {
        errors[lessonId] = caught instanceof Error && caught.name === 'TimeoutError'
          ? '等待超过 2 分钟，请检查模型服务后重试。'
          : caught instanceof Error ? caught.message : '生成失败';
        setFailures({ ...errors });
      }
    }
    setProgress('');
    setPhase('review');
  };

  const approve = async () => {
    if (!action || !plan || !canSave || busy) return;
    setPhase('saving');
    setError(null);
    try {
      const response = await fetch(endpoint, {
        method: 'PATCH', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ lessons: lessons.map(({ lessonId, drafts, baseVersion }) => ({ lessonId, drafts, baseVersion })) }),
      });
      const data = await response.json();
      if (!response.ok || data.success === false) throw new Error(data.error || '保存失败');
      setPhase('saved');
      sessionStorage.removeItem(`teacher-plan:${plan.id}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '保存失败');
      setPhase('review');
    }
  };

  const previewUrl = (lesson: LessonDraft) =>
    `/course-space/${encodeURIComponent(courseId)}/lesson-files/preview?lessonId=${encodeURIComponent(lesson.lessonId)}&types=${encodeURIComponent(lesson.drafts.map((draft) => draft.type).join(','))}`;

  return <main className="min-h-screen bg-slate-50 px-4 py-8 text-slate-900">
    <div className="mx-auto max-w-4xl space-y-5">
      <header className="rounded-2xl border bg-white p-5 shadow-sm">
        <button type="button" disabled={busy} onClick={() => router.push(`/course-space?workspace=${encodeURIComponent(courseId)}`)} className="text-sm text-[#B00055] disabled:opacity-50">← 返回教师工作台</button>
        <h1 className="mt-3 text-2xl font-semibold">课时内容生成与审核</h1>
        <p className="mt-1 text-sm text-slate-500">确认计划 → 生成草稿 → 教师审核 → 统一保存并预览</p>
      </header>
      {error && <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div>}
      {phase === 'confirm' && action && <section className="rounded-2xl border bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold">确认备课任务 · {action.lessonIds.length} 个课时</h2>
        <p className="mt-3 text-sm leading-7">{plan?.summary}</p>
        <p className="mt-2 text-sm text-slate-500">教师指令：{action.instruction}</p>
        <p className="mt-2 text-xs text-slate-500">确认后只生成待审核草稿；审核通过前不会覆盖课时文件。批量生成必须全部成功后才能统一保存。</p>
        <button type="button" onClick={() => void generate()} className="mt-5 rounded-lg bg-[#B00055] px-5 py-2 text-sm font-medium text-white">确认并生成草稿</button>
      </section>}
      {phase === 'generating' && <section role="status" className="rounded-2xl border bg-white p-6 text-sm shadow-sm">{progress || '正在准备生成课时草稿…'}</section>}
      {(phase === 'review' || phase === 'saving') && <section className="space-y-5 rounded-2xl border bg-white p-6 shadow-sm">
        <div><h2 className="text-lg font-semibold">审核生成内容 · {lessons.length}/{action?.lessonIds.length} 个课时</h2><p className="text-sm text-slate-500">可以修改正文；审核通过后统一写入。取消或生成失败不会改变原文件。</p></div>
        {Object.entries(failures).map(([lessonId, message]) => <div role="alert" key={lessonId} className="rounded-lg bg-red-50 p-3 text-sm text-red-700">课时 {lessonId}：{message}</div>)}
        {lessons.map((lesson) => <fieldset key={lesson.lessonId} disabled={busy} className="space-y-4 rounded-xl border p-4">
          <legend className="px-2 font-semibold">{lesson.lessonTitle}</legend>
          {lesson.drafts.map((draft) => <label key={draft.type} className="block space-y-2 text-sm font-medium">
            <span>{draft.title}</span>
            <textarea value={draft.content} onChange={(event) => setLessons((current) => current.map((item) => item.lessonId === lesson.lessonId ? { ...item, drafts: item.drafts.map((value) => value.type === draft.type ? { ...value, content: event.target.value } : value) } : item))} rows={Math.max(10, Math.min(20, draft.content.split('\n').length + 3))} className="w-full rounded-lg border border-slate-200 p-3 font-normal leading-6 outline-none focus:border-[#B00055]" />
            {draft.content.length > 30000 && <span className="text-red-700">正文不能超过 30000 字。</span>}
          </label>)}
        </fieldset>)}
        <div className="flex flex-wrap gap-3">
          <button type="button" disabled={busy || !canSave} onClick={() => void approve()} className="rounded-lg bg-[#B00055] px-5 py-2 text-sm font-medium text-white disabled:opacity-50">{phase === 'saving' ? '保存中…' : '审核通过并统一保存'}</button>
          {Object.keys(failures).length > 0 && <button type="button" disabled={busy} onClick={() => void generate(true)} className="rounded-lg border px-5 py-2 text-sm">重试失败课时（保留已编辑草稿）</button>}
          <button type="button" disabled={busy} onClick={() => { if (window.confirm('重新生成将丢弃当前草稿修改，但不会改变已保存的原文件。是否继续？')) void generate(); }} className="rounded-lg border px-5 py-2 text-sm">重新生成全部</button>
          <button type="button" disabled={busy} onClick={() => router.push(`/course-space?workspace=${encodeURIComponent(courseId)}`)} className="rounded-lg border px-5 py-2 text-sm">取消，不保存</button>
        </div>
      </section>}
      {phase === 'saved' && <section className="space-y-4 rounded-2xl border bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold">已审核保存 {lessons.length} 个课时</h2>
        {lessons.map((lesson) => <a key={lesson.lessonId} href={previewUrl(lesson)} className="block text-sm text-[#B00055] underline">预览 {lesson.lessonTitle}</a>)}
      </section>}
    </div>
  </main>;
}