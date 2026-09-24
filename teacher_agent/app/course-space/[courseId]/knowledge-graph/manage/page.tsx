'use client';

import { use, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { ArrowLeft } from 'lucide-react';
import { CourseIntelligencePanel } from '@/components/course-space/course-intelligence-panel';
import type { CourseSpace } from '@/lib/course-space';

export default function CourseKnowledgeGraphManagePage({ params }: { params: Promise<{ courseId: string }> }) {
  const { courseId } = use(params);
  const router = useRouter();
  const [course, setCourse] = useState<CourseSpace | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    void fetch(`/api/course-space/${encodeURIComponent(courseId)}`, { cache: 'no-store' })
      .then(async (response) => {
        const data = await response.json();
        if (!response.ok || data.success === false || !data.course) throw new Error(data.error || '读取课程失败');
        setCourse(data.course);
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : String(reason)));
  }, [courseId]);

  return <main className="min-h-screen bg-slate-50 px-4 py-6 text-slate-900">
    <div className="mx-auto max-w-4xl">
      <header className="mb-5 flex items-center gap-3">
        <button type="button" onClick={() => router.push(`/course-space?workspace=${encodeURIComponent(courseId)}`)} className="rounded-full bg-white p-2 shadow-sm hover:bg-slate-100" aria-label="返回教师工作区"><ArrowLeft className="size-5" /></button>
        <div><h1 className="text-xl font-semibold">课程知识图谱</h1><p className="text-sm text-muted-foreground">建立骨架、抽取知识点与课时关系，并进入教师审核</p></div>
      </header>
      {error ? <p className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</p> : course ? <CourseIntelligencePanel course={course} artifacts={[]} graphOnly /> : <p className="text-sm text-muted-foreground">正在读取课程…</p>}
    </div>
  </main>;
}
