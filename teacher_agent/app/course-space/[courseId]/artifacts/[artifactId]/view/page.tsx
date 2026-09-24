'use client';

import { useCallback, useEffect, useState } from 'react';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import { ArrowLeft, ExternalLink } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { ArtifactHtmlReview } from '@/components/course-space/artifact-html-review';
import type { CourseArtifactRecord, CourseSpace } from '@/lib/course-space';

export default function FullScreenArtifactPage() {
  const { courseId, artifactId } = useParams<{ courseId: string; artifactId: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [course, setCourse] = useState<CourseSpace>();
  const [artifact, setArtifact] = useState<CourseArtifactRecord>();
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      const response = await fetch(`/api/course-space/${courseId}`, { cache: 'no-store' });
      const data = await response.json();
      if (!response.ok || data.success === false) throw new Error(data.error || '读取产物失败');
      const found = (data.artifacts as CourseArtifactRecord[]).find(
        (item) => item.id === artifactId,
      );
      if (!found) throw new Error('未找到该教学产物');
      setCourse(data.course);
      setArtifact(found);
      setError('');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }, [artifactId, courseId]);

  useEffect(() => {
    void load();
  }, [load]);

  const goBack = () => {
    const source = searchParams.get('from');
    if (source?.startsWith('/') && !source.startsWith('//')) {
      router.push(source);
      return;
    }
    if (window.history.length > 1) {
      router.back();
      return;
    }
    router.push(`/course-space?workspace=${encodeURIComponent(courseId)}`);
  };
  const source = searchParams.get('from');
  const reviewUrl = `/course-space/${courseId}/review/${artifactId}${
    source?.startsWith('/') && !source.startsWith('//') ? `?from=${encodeURIComponent(source)}` : ''
  }`;

  return (
    <main className="flex h-screen min-h-0 flex-col overflow-hidden bg-[radial-gradient(circle_at_top,#eef3ff,transparent_45%),#f8fafc] text-slate-900">
      <header className="flex shrink-0 items-center justify-between gap-4 border-b bg-white/95 px-5 py-3 shadow-sm backdrop-blur-xl">
        <div className="flex min-w-0 items-center gap-3">
          <Button
            variant="ghost"
            size="icon"
            className="shrink-0 rounded-full"
            aria-label="返回上一级"
            onClick={goBack}
          >
            <ArrowLeft />
          </Button>
          <div className="min-w-0">
            <h1 className="truncate text-lg font-semibold">
              {artifact?.title || '可视化教学产物'}
            </h1>
            <p className="truncate text-xs text-muted-foreground">
              {course?.title || '课程'} · 全屏 HTML 预览
              {artifact ? ` · 来源引用 ${artifact.citations.length} 条` : ''}
            </p>
          </div>
        </div>
        <div className="flex shrink-0 gap-2">
          <Button variant="outline" onClick={() => router.push(reviewUrl)}>
            进入编辑与审核
          </Button>
          {artifact?.classroomUrl && (
            <Button asChild>
              <a href={artifact.classroomUrl} target="_blank" rel="noreferrer">
                打开互动课件
                <ExternalLink className="ml-2 size-4" />
              </a>
            </Button>
          )}
        </div>
      </header>
      <section className="flex min-h-0 flex-1 p-4 lg:p-6">
        {artifact ? (
          <ArtifactHtmlReview artifact={artifact} onChange={() => {}} fullScreen readOnly />
        ) : (
          <div className="flex flex-1 items-center justify-center rounded-2xl border bg-white text-muted-foreground">
            {error || '正在读取产物…'}
          </div>
        )}
      </section>
    </main>
  );
}
