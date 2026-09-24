'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import type { CourseLessonFile, CourseSpace } from '@/lib/course-space/types';

export default function LessonFilePreviewPage() {
  const { courseId } = useParams<{ courseId: string }>();
  const router = useRouter();
  const [title, setTitle] = useState('');
  const [files, setFiles] = useState<CourseLessonFile[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const lessonId = params.get('lessonId');
    const types = new Set((params.get('types') || '').split(',').filter(Boolean));
    const load = async () => {
        if (!lessonId) throw new Error('缺少课时标识');
        const response = await fetch(`/api/course-space/${encodeURIComponent(courseId)}`, { cache: 'no-store' });
        const data = await response.json();
        if (!response.ok || data.success === false) throw new Error(data.error || '读取课程失败');
        const course = data.course as CourseSpace;
        const lesson = course.modules.flatMap((module) => module.lessons).find((item) => item.id === lessonId);
        if (!lesson) throw new Error('课时不存在');
        setTitle(`${course.title} / ${lesson.title}`);
        setFiles((lesson.files ?? []).filter((file) => types.size === 0 || types.has(file.type)));
    };
    void load().catch((caught) => setError(caught instanceof Error ? caught.message : '读取失败'));
  }, [courseId]);

  return <main className="min-h-screen bg-slate-50 px-4 py-8 text-slate-900"><div className="mx-auto max-w-4xl space-y-5">
    <header className="rounded-2xl border bg-white p-5 shadow-sm">
      <button type="button" onClick={() => router.push(`/course-space?workspace=${encodeURIComponent(courseId)}`)} className="text-sm text-[#B00055]">← 返回教师工作台</button>
      <h1 className="mt-3 text-2xl font-semibold">已审核课时内容预览</h1>
      <p className="mt-1 text-sm text-slate-500">{title || '正在读取课程文件…'}</p>
    </header>
    {error && <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div>}
    {!error && files.map((file) => <article key={file.id} className="rounded-2xl border bg-white p-6 shadow-sm"><h2 className="text-lg font-semibold">{file.title}</h2><p className="mt-1 text-xs text-emerald-700">审核通过 · 已保存至课时文件夹</p><div className="mt-5 whitespace-pre-wrap leading-8 text-sm">{file.content}</div></article>)}
    {!error && title && files.length === 0 && <p className="rounded-xl border bg-white p-5 text-sm text-slate-500">该课时暂无对应文件，请返回工作台重新检查。</p>}
  </div></main>;
}
