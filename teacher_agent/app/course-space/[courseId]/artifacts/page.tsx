'use client';

import { useCallback, useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { ArrowLeft, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { ArtifactGallery } from '@/components/course-space/artifact-gallery';
import type { CourseArtifactRecord, CourseSpace } from '@/lib/course-space';

export default function CourseArtifactsPage() {
  const { courseId } = useParams<{ courseId: string }>();
  const router = useRouter();
  const [course, setCourse] = useState<CourseSpace>();
  const [artifacts, setArtifacts] = useState<CourseArtifactRecord[]>([]);
  const [error, setError] = useState('');
  const load = useCallback(async () => {
    try {
      const response = await fetch(`/api/course-space/${courseId}`, { cache: 'no-store' });
      const data = await response.json();
      if (!response.ok || data.success === false) throw new Error(data.error || '读取产物失败');
      setCourse(data.course);
      setArtifacts(data.artifacts);
      setError('');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }, [courseId]);
  useEffect(() => {
    void load();
  }, [load]);
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
            <h1 className="text-xl font-semibold">生成产物</h1>
            <p className="text-sm text-muted-foreground">
              {course?.title || '课程'} · HTML、Word 与互动课件资源库
            </p>
          </div>
        </div>
        <Button variant="outline" onClick={() => void load()}>
          <RefreshCw className="mr-2 size-4" />
          刷新
        </Button>
      </header>
      <section className="mx-auto max-w-7xl p-6">
        <div className="mb-6">
          <h2 className="text-2xl font-semibold">本课程已生成产物</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            点击卡片进入独立 HTML 查看、编辑、审核与发布页面。
          </p>
        </div>
        <ArtifactGallery courseId={courseId} artifacts={artifacts} />
        {error && (
          <div className="mt-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            {error}
          </div>
        )}
      </section>
    </main>
  );
}
