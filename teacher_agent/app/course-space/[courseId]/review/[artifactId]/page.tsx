'use client';

import { useCallback, useEffect, useState } from 'react';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import { ArrowLeft, ExternalLink, PackageCheck } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ArtifactHtmlReview } from '@/components/course-space/artifact-html-review';
import type { CourseArtifactRecord, CourseSpace } from '@/lib/course-space';

export default function ArtifactReviewPage() {
  const { courseId, artifactId } = useParams<{ courseId: string; artifactId: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [course, setCourse] = useState<CourseSpace>();
  const [artifact, setArtifact] = useState<CourseArtifactRecord>();
  const [message, setMessage] = useState('');
  const load = useCallback(async () => {
    const response = await fetch(`/api/course-space/${courseId}`, { cache: 'no-store' });
    const data = await response.json();
    if (!response.ok || data.success === false) throw new Error(data.error || '读取产物失败');
    setCourse(data.course);
    setArtifact(data.artifacts.find((item: CourseArtifactRecord) => item.id === artifactId));
  }, [artifactId, courseId]);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load().catch((error) => setMessage(error.message));
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

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
    if (!response.ok || data.success === false) return setMessage(data.error || '保存失败');
    setArtifact(data.artifact);
    setMessage(action === 'approve' ? '审核通过，已进入发布候选集。' : '修改已保存。');
  };
  const publish = async () => {
    const response = await fetch(`/api/course-space/${courseId}/publish`, { method: 'POST' });
    const data = await response.json();
    setMessage(
      response.ok && data.success !== false
        ? `知识包 v${data.knowledgePackage.version} 已发布。`
        : data.error || '发布失败',
    );
  };
  const source = searchParams.get('from');
  const previewUrl = `/course-space/${courseId}/artifacts/${artifactId}/view${
    source?.startsWith('/') && !source.startsWith('//') ? `?from=${encodeURIComponent(source)}` : ''
  }`;

  return (
    <main className="min-h-screen bg-slate-50 text-slate-900">
      <header className="flex items-center justify-between border-b bg-white px-6 py-4">
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="icon"
            aria-label="返回产物预览"
            onClick={() => router.push(previewUrl)}
          >
            <ArrowLeft />
          </Button>
          <div>
            <h1 className="text-xl font-semibold">逐产物审核与发布</h1>
            <p className="text-sm text-muted-foreground">{course?.title} · 独立 HTML 审核页面</p>
          </div>
        </div>
        {artifact?.classroomUrl && (
          <Button variant="outline" asChild>
            <a href={artifact.classroomUrl} target="_blank">
              打开互动课件
              <ExternalLink className="ml-2 size-4" />
            </a>
          </Button>
        )}
      </header>
      <section className="mx-auto max-w-6xl p-6">
        {artifact ? (
          <div className="space-y-4">
            <div className="rounded-xl border bg-white p-5">
              <div className="flex items-start justify-between">
                <div>
                  <h2 className="text-2xl font-semibold">{artifact.title}</h2>
                  <p className="mt-1 text-sm text-muted-foreground">
                    状态：{artifact.status} · 来源引用 {artifact.citations.length} 条
                  </p>
                </div>
                <span className="rounded-full bg-violet-50 px-3 py-1 text-sm text-violet-700">
                  HTML + Word 双格式
                </span>
              </div>
            </div>
            <ArtifactHtmlReview
              artifact={artifact}
              onChange={(content) => setArtifact({ ...artifact, content })}
            />
            <div className="rounded-xl border bg-white p-5">
              <Input
                placeholder="审核说明（可选）"
                value={artifact.reviewerNote || ''}
                onChange={(event) => setArtifact({ ...artifact, reviewerNote: event.target.value })}
              />
              <div className="mt-4 flex flex-wrap gap-2">
                <Button variant="outline" onClick={() => void review('save')}>
                  保存修改
                </Button>
                <Button onClick={() => void review('approve')}>审核通过</Button>
                <Button variant="secondary" onClick={() => void publish()}>
                  <PackageCheck className="mr-2 size-4" />
                  发布审核后的知识包
                </Button>
              </div>
            </div>
          </div>
        ) : (
          <div className="rounded-xl border bg-white p-8 text-center text-muted-foreground">
            正在读取产物…
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
