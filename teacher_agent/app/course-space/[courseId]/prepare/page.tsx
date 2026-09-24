'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import type { TeacherOperationPlan } from '@/lib/course-space/teacher-agent-intent';
import type { CourseLessonFileType } from '@/lib/course-space/types';

type Draft = { type: CourseLessonFileType; title: string; content: string };
type Phase = 'confirm' | 'generating' | 'review' | 'saving';

export default function TeacherPreparationPage() {
  const { courseId } = useParams<{ courseId: string }>();
  const router = useRouter();
  const [plan, setPlan] = useState<TeacherOperationPlan | null>(null);
  const [phase, setPhase] = useState<Phase>('confirm');
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [lessonTitle, setLessonTitle] = useState('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const draftId = new URLSearchParams(window.location.search).get('draft');
    if (!draftId) return setError('缺少备课任务标识，请返回工作台重新提交命令。');
    const raw = sessionStorage.getItem(`teacher-plan:${draftId}`);
    if (!raw) return setError('备课计划已失效，请返回工作台重新提交命令。');
    try {
      const parsed = JSON.parse(raw) as TeacherOperationPlan;
      if (parsed.action?.type !== 'create-lesson-files' || parsed.action.lessonIds.length !== 1 || !parsed.action.populateContent) {
        throw new Error('该命令不能在课时内容审核页执行');
      }
      setPlan(parsed);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '备课计划无效');
    }
  }, []);

  const action = plan?.action?.type === 'create-lesson-files' ? plan.action : null;
  const generate = async () => {
    if (!action) return;
    setPhase('generating');
    setError(null);
    try {
      const response = await fetch(`/api/course-space/${encodeURIComponent(courseId)}/lesson-files/draft`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ lessonId: action.lessonIds[0], fileTypes: action.fileTypes, instruction: action.instruction }),
        signal: AbortSignal.timeout(120000),
      });
      const data = await response.json();
      if (!response.ok || data.success === false) throw new Error(data.error || '生成失败');
      setLessonTitle(data.lessonTitle);
      setDrafts(data.drafts);
      setPhase('review');
    } catch (caught) {
      setError(caught instanceof Error && caught.name === 'TimeoutError' ? '生成等待超过 2 分钟，请检查模型服务后重试。' : caught instanceof Error ? caught.message : '生成失败');
      setPhase('confirm');
    }
  };

  const approve = async () => {
    if (!action || !drafts.length) return;
    setPhase('saving');
    setError(null);
    try {
      const response = await fetch(`/api/course-space/${encodeURIComponent(courseId)}/lesson-files/draft`, {
        method: 'PATCH',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ lessonId: action.lessonIds[0], drafts }),
      });
      const data = await response.json();
      if (!response.ok || data.success === false) throw new Error(data.error || '保存失败');
      router.push(`/course-space/${encodeURIComponent(courseId)}/lesson-files/preview?lessonId=${encodeURIComponent(action.lessonIds[0])}&types=${encodeURIComponent(drafts.map((draft) => draft.type).join(','))}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '保存失败');
      setPhase('review');
    }
  };

  return <main className="min-h-screen bg-slate-50 px-4 py-8 text-slate-900">
    <div className="mx-auto max-w-4xl space-y-5">
      <header className="rounded-2xl border bg-white p-5 shadow-sm">
        <button type="button" onClick={() => router.push(`/course-space?workspace=${encodeURIComponent(courseId)}`)} className="text-sm text-[#B00055]">← 返回教师工作台</button>
        <h1 className="mt-3 text-2xl font-semibold">课时内容生成与审核</h1>
        <p className="mt-1 text-sm text-slate-500">确认计划 → 生成草稿 → 教师审核 → 预览已保存内容</p>
      </header>
      {error && <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div>}
      {phase === 'confirm' && action && <section className="rounded-2xl border bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold">确认备课任务</h2>
        <p className="mt-3 text-sm leading-7">{plan?.summary}</p>
        <p className="mt-2 text-sm text-slate-500">教师指令：{action.instruction}</p>
        <p className="mt-2 text-xs text-slate-500">确认后只生成待审核草稿；审核通过前不会覆盖课时文件。</p>
        <button type="button" onClick={() => void generate()} className="mt-5 rounded-lg bg-[#B00055] px-5 py-2 text-sm font-medium text-white">确认并生成草稿</button>
      </section>}
      {phase === 'generating' && <section role="status" className="rounded-2xl border bg-white p-6 text-sm shadow-sm">正在依据课程材料生成草稿，请稍候；生成完成后会进入审核，不会自动覆盖原文件。</section>}
      {(phase === 'review' || phase === 'saving') && <section className="space-y-4 rounded-2xl border bg-white p-6 shadow-sm">
        <div><h2 className="text-lg font-semibold">审核生成内容</h2><p className="text-sm text-slate-500">{lessonTitle} · 可修改正文；审核通过后写入课时文件。</p></div>
        {drafts.map((draft, index) => <label key={draft.type} className="block space-y-2 text-sm font-medium"><span>{draft.title}</span><textarea value={draft.content} onChange={(event) => setDrafts((current) => current.map((item, position) => position === index ? { ...item, content: event.target.value } : item))} rows={Math.max(10, Math.min(20, draft.content.split('\n').length + 3))} className="w-full rounded-lg border border-slate-200 p-3 font-normal leading-6 outline-none focus:border-[#B00055]"/></label>)}
        <div className="flex gap-3"><button type="button" disabled={phase === 'saving' || drafts.some((draft) => !draft.content.trim())} onClick={() => void approve()} className="rounded-lg bg-[#B00055] px-5 py-2 text-sm font-medium text-white disabled:opacity-50">{phase === 'saving' ? '保存中…' : '审核通过并保存'}</button><button type="button" disabled={phase === 'saving'} onClick={() => void generate()} className="rounded-lg border px-5 py-2 text-sm">重新生成</button></div>
      </section>}
    </div>
  </main>;
}
