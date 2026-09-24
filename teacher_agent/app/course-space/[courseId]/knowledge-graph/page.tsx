'use client';

import { use, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { ArrowLeft, CheckCircle2, FileSearch, GitBranch, LoaderCircle, Network } from 'lucide-react';
import { Button } from '@/components/ui/button';
import type { CourseKnowledgeGraph } from '@/lib/course-space';

export default function CourseKnowledgeGraphReviewPage({ params }: { params: Promise<{ courseId: string }> }) {
  const { courseId } = use(params);
  const router = useRouter();
  const [graph, setGraph] = useState<CourseKnowledgeGraph | null>(null);
  const [loading, setLoading] = useState(true);
  const [publishing, setPublishing] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    void fetch(`/api/course-space/${courseId}/knowledge-graph`, { cache:'no-store' })
      .then((response) => response.json().then((data) => ({ response, data })))
      .then(({ response, data }) => {
        if (!response.ok || !data.graph) throw new Error(data.error || '知识图谱不存在');
        setGraph(data.graph);
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : String(reason)))
      .finally(() => setLoading(false));
  }, [courseId]);
  const concepts = useMemo(() => graph?.nodes.filter((node) => node.type === 'knowledge-point') ?? [], [graph]);
  const objectives = useMemo(() => graph?.nodes.filter((node) => node.type === 'learning-objective') ?? [], [graph]);
  const prerequisites = useMemo(() => graph?.edges.filter((edge) => edge.type === 'prerequisite-of') ?? [], [graph]);
  const approveAndPublish = async () => {
    if (!graph) return;
    setPublishing(true); setError('');
    try {
      const reviewed: CourseKnowledgeGraph = { ...graph, nodes:graph.nodes.map((node) =>
        node.type === 'knowledge-point' || node.type === 'learning-objective'
          ? { ...node, status:'approved' as const, updatedAt:Date.now() } : node) };
      const saved = await fetch(`/api/course-space/${courseId}/knowledge-graph`, {
        method:'PUT', headers:{ 'content-type':'application/json' }, body:JSON.stringify(reviewed),
      });
      const savedData = await saved.json();
      if (!saved.ok || savedData.success === false) throw new Error(savedData.error || '保存审核结果失败');
      const response = await fetch(`/api/course-space/${courseId}/knowledge-graph/publish`, {
        method:'POST', headers:{ 'content-type':'application/json' }, body:JSON.stringify({ version:graph.version }),
      });
      const data = await response.json();
      if (!response.ok || data.success === false) throw new Error(data.error || '发布知识图谱失败');
      setGraph(data.graph);
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setPublishing(false); }
  };
  if (loading) return <main className="flex min-h-screen items-center justify-center"><LoaderCircle className="size-6 animate-spin text-[#B00055]"/></main>;
  return <main className="min-h-screen bg-[radial-gradient(circle_at_20%_0%,rgba(176,0,85,.08),transparent_32%),#f7f8fb] px-6 py-5">
    <div className="mx-auto max-w-[1500px]">
      <header className="mb-5 flex items-center justify-between rounded-2xl border bg-white/90 px-5 py-4 shadow-sm"><div className="flex items-center gap-3"><button onClick={() => router.push(`/course-space?workspace=${courseId}`)} className="rounded-full p-2 hover:bg-slate-100"><ArrowLeft className="size-5"/></button><div><h1 className="text-xl font-bold">课程知识图谱审核</h1><p className="text-xs text-muted-foreground">核对知识点、课程目标、先修关系、课时对齐及原始页码证据</p></div></div>{graph && <span className="rounded-full bg-[#B00055]/10 px-3 py-1 text-xs text-[#B00055]">v{graph.version} · {graph.status}</span>}</header>
      {error && <p className="mb-4 rounded-xl bg-red-50 p-3 text-sm text-red-700">{error}</p>}
      {graph && <div className="grid gap-5 lg:grid-cols-[1fr_1fr_340px]">
        <section className="rounded-2xl border bg-white p-5 shadow-sm"><h2 className="flex items-center gap-2 font-semibold"><Network className="size-4 text-[#B00055]"/>知识点 · {concepts.length}</h2><div className="mt-4 space-y-3">{concepts.map((node) => <article key={node.id} className="rounded-xl border p-4"><h3 className="font-medium">{node.title}</h3><p className="mt-1 text-sm leading-6 text-slate-600">{node.description || '—'}</p><div className="mt-3 flex flex-wrap gap-2">{node.evidence.map((evidence) => <span key={evidence.id} className="rounded bg-amber-50 px-2 py-1 text-[11px] text-amber-700"><FileSearch className="mr-1 inline size-3"/>第 {evidence.page ?? '?'} 页</span>)}</div></article>)}</div></section>
        <section className="rounded-2xl border bg-white p-5 shadow-sm"><h2 className="flex items-center gap-2 font-semibold"><CheckCircle2 className="size-4 text-[#B00055]"/>课程目标 · {objectives.length}</h2><div className="mt-4 space-y-3">{objectives.map((node) => <article key={node.id} className="rounded-xl border p-4"><h3 className="font-medium">{node.title}</h3><p className="mt-1 text-sm leading-6 text-slate-600">{node.description || '—'}</p><p className="mt-3 text-xs text-muted-foreground">对齐课时：{(node.properties.lessonIds as string[] | undefined)?.length ?? 0} · 来源证据：{node.evidence.length}</p></article>)}</div></section>
        <aside className="space-y-4"><div className="rounded-2xl border bg-white p-5 shadow-sm"><h2 className="flex items-center gap-2 font-semibold"><GitBranch className="size-4 text-[#B00055]"/>关系检查</h2><dl className="mt-4 grid grid-cols-2 gap-3 text-center"><div className="rounded-xl bg-slate-50 p-3"><dt className="text-xs text-muted-foreground">先修关系</dt><dd className="mt-1 text-xl font-bold">{prerequisites.length}</dd></div><div className="rounded-xl bg-slate-50 p-3"><dt className="text-xs text-muted-foreground">全部关系</dt><dd className="mt-1 text-xl font-bold">{graph.edges.length}</dd></div></dl><p className="mt-4 text-xs leading-5 text-muted-foreground">发布后，学生智能体只能通过标准接口读取这个已审核版本，并保留材料、页码和哈希引用。</p><Button className="mt-4 w-full bg-[#B00055] hover:bg-[#8F0046]" disabled={publishing || graph.status === 'published' || concepts.length === 0} onClick={() => void approveAndPublish()}>{publishing && <LoaderCircle className="mr-2 size-4 animate-spin"/>}{graph.status === 'published' ? '已审核并发布' : '审核通过并发布'}</Button></div></aside>
      </div>}
    </div>
  </main>;
}
