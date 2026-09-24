'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  BookOpenCheck,
  Database,
  ExternalLink,
  FileText,
  LoaderCircle,
  Network,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import type {
  CourseArtifactRecord,
  CourseKnowledgeExtractionJob,
  CourseKnowledgeGraph,
  CourseSpace,
} from '@/lib/course-space';

type Tab = 'graph' | 'artifacts';

export function CourseIntelligencePanel({
  course,
  artifacts,
  graphOnly = false,
}: {
  course: CourseSpace;
  artifacts: CourseArtifactRecord[];
  graphOnly?: boolean;
}) {
  const router = useRouter();
  const [tab, setTab] = useState<Tab>('graph');
  const [graph, setGraph] = useState<CourseKnowledgeGraph | null>(null);
  const [extractionJob, setExtractionJob] = useState<CourseKnowledgeExtractionJob | null>(null);
  const [databaseConfigured, setDatabaseConfigured] = useState(false);
  const [storageMode, setStorageMode] = useState<'postgresql' | 'local-json'>('local-json');
  const [loading, setLoading] = useState(true);
  const [building, setBuilding] = useState(false);
  const [error, setError] = useState('');
  const load = async () => {
    setLoading(true);
    try {
      const [graphResponse, jobsResponse] = await Promise.all([
        fetch(`/api/course-space/${course.id}/knowledge-graph`, { cache: 'no-store' }),
        fetch(`/api/course-space/${course.id}/knowledge-graph/extract`, { cache: 'no-store' }),
      ]);
      const [data, jobsData] = await Promise.all([graphResponse.json(), jobsResponse.json()]);
      if (!graphResponse.ok || data.success === false)
        throw new Error(data.error || '读取知识图谱失败');
      setGraph(data.graph);
      setDatabaseConfigured(Boolean(data.databaseConfigured));
      setStorageMode(data.storageMode === 'postgresql' ? 'postgresql' : 'local-json');
      setExtractionJob(jobsResponse.ok ? (jobsData.jobs?.[0] ?? null) : null);
      setError('');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    void load();
  }, [course.id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!extractionJob || !['queued', 'running'].includes(extractionJob.status)) return;
    const timer = window.setInterval(async () => {
      const response = await fetch(`/api/course-space/knowledge-graph/jobs/${extractionJob.id}`, {
        cache: 'no-store',
      });
      const data = await response.json();
      if (!response.ok || !data.job) return;
      setExtractionJob(data.job);
      if (data.job.status === 'review' || data.job.status === 'failed') void load();
    }, 1800);
    return () => window.clearInterval(timer);
  }, [extractionJob?.id, extractionJob?.status]); // eslint-disable-line react-hooks/exhaustive-deps
  const counts = useMemo(
    () => ({
      knowledge: graph?.nodes.filter((node) => node.type === 'knowledge-point').length ?? 0,
      objectives: graph?.nodes.filter((node) => node.type === 'learning-objective').length ?? 0,
      lessons: graph?.nodes.filter((node) => node.type === 'lesson').length ?? 0,
      evidence: graph?.nodes.reduce((sum, node) => sum + node.evidence.length, 0) ?? 0,
    }),
    [graph],
  );
  const extractionStale = Boolean(
    extractionJob &&
    extractionJob.status === 'running' &&
    Date.now() - extractionJob.updatedAt > 2 * 60_000,
  );
  const bootstrap = async () => {
    setBuilding(true);
    setError('');
    try {
      const response = await fetch(`/api/course-space/${course.id}/knowledge-graph`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ action: 'bootstrap', teacherId: course.teacherId }),
      });
      const data = await response.json();
      if (!response.ok || data.success === false) throw new Error(data.error || '创建图谱失败');
      setGraph(data.graph);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBuilding(false);
    }
  };
  const extract = async () => {
    setBuilding(true);
    setError('');
    try {
      const response = await fetch(`/api/course-space/${course.id}/knowledge-graph/extract`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ teacherId: course.teacherId }),
      });
      const data = await response.json();
      if (!response.ok || data.success === false) throw new Error(data.error || '启动知识抽取失败');
      setExtractionJob(data.job);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBuilding(false);
    }
  };
  const retryExtraction = async () => {
    if (!extractionJob) return;
    setBuilding(true);
    setError('');
    try {
      const response = await fetch(`/api/course-space/knowledge-graph/jobs/${extractionJob.id}`, {
        method: 'POST',
      });
      const data = await response.json();
      if (!response.ok || data.success === false) throw new Error(data.error || '恢复知识抽取失败');
      setExtractionJob(data.job);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBuilding(false);
    }
  };

  return (
    <aside
      className={`flex min-h-0 flex-col overflow-hidden rounded-[24px] border border-white/80 bg-white/88 shadow-[0_24px_70px_-38px_rgba(79,18,49,.45)] backdrop-blur-xl ${graphOnly ? 'h-auto' : 'h-[calc(100vh-105px)]'}`}
    >
      <div className="border-b px-4 pt-4">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <div className="rounded-xl bg-[#B00055]/10 p-2 text-[#B00055]">
              <Database className="size-4" />
            </div>
            <div>
              <h3 className="text-sm font-semibold">课程知识图谱</h3>
              <p className="text-[11px] text-muted-foreground">知识点、课时关系与来源证据</p>
            </div>
          </div>
          <span className="rounded-full bg-emerald-50 px-2 py-1 text-[9px] text-emerald-700">
            {storageMode === 'postgresql' ? 'PostgreSQL' : '本地持久化'}
          </span>
        </div>
        {!graphOnly && (
          <div className="mt-4 grid grid-cols-2 gap-1 rounded-xl bg-slate-100 p-1">
            <button
              onClick={() => setTab('graph')}
              className={`rounded-lg px-3 py-2 text-xs ${tab === 'graph' ? 'bg-white font-medium text-[#B00055] shadow-sm' : 'text-slate-500'}`}
            >
              知识图谱
            </button>
            <button
              onClick={() => setTab('artifacts')}
              className={`rounded-lg px-3 py-2 text-xs ${tab === 'artifacts' ? 'bg-white font-medium text-[#B00055] shadow-sm' : 'text-slate-500'}`}
            >
              历史产物 · {artifacts.length}
            </button>
          </div>
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {tab === 'graph' ? (
          <div className="space-y-4">
            {loading ? (
              <div className="flex items-center gap-2 py-10 text-sm text-muted-foreground">
                <LoaderCircle className="size-4 animate-spin" />
                读取课程图谱…
              </div>
            ) : graph ? (
              <>
                <div className="rounded-2xl bg-gradient-to-br from-[#B00055] to-[#6f2148] p-4 text-white">
                  <div className="flex items-center justify-between">
                    <Network className="size-5" />
                    <span className="rounded-full bg-white/15 px-2 py-1 text-[10px]">
                      v{graph.version} · {graph.status}
                    </span>
                  </div>
                  <h4 className="mt-5 font-semibold">{graph.title}</h4>
                  <p className="mt-1 line-clamp-3 text-xs leading-5 text-white/70">
                    {graph.summary}
                  </p>
                </div>
                <div className="grid grid-cols-4 gap-2">
                  {[
                    [counts.knowledge, '知识点'],
                    [counts.objectives, '目标'],
                    [counts.lessons, '课时'],
                    [counts.evidence, '引用'],
                  ].map(([value, label]) => (
                    <div key={String(label)} className="rounded-xl bg-slate-50 p-3 text-center">
                      <b className="block text-lg">{value}</b>
                      <span className="text-[10px] text-muted-foreground">{label}</span>
                    </div>
                  ))}
                </div>
                <div className="rounded-2xl border bg-slate-50 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <div>
                      <p className="text-xs font-medium">知识抽取 Job</p>
                      <p className="mt-1 text-[10px] text-muted-foreground">
                        {extractionStale
                          ? '任务响应超时，可安全恢复抽取'
                          : (extractionJob?.message ?? '从图谱骨架抽取知识点、目标和课时关系')}
                      </p>
                    </div>
                    {extractionJob && (
                      <span className="text-[10px] text-[#B00055]">{extractionJob.progress}%</span>
                    )}
                  </div>
                  {extractionJob && ['queued', 'running'].includes(extractionJob.status) && (
                    <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-slate-200">
                      <div
                        className="h-full bg-[#B00055] transition-all"
                        style={{ width: `${extractionJob.progress}%` }}
                      />
                    </div>
                  )}
                  {graph.status === 'review' ? (
                    <Button
                      className="mt-3 w-full bg-[#B00055] hover:bg-[#8F0046]"
                      onClick={() => router.push(`/course-space/${course.id}/knowledge-graph`)}
                    >
                      进入教师审核
                    </Button>
                  ) : graph.status === 'published' ? (
                    <Button
                      className="mt-3 w-full bg-[#B00055] hover:bg-[#8F0046]"
                      disabled={building}
                      onClick={() => void extract()}
                    >
                      {building && <LoaderCircle className="mr-2 size-4 animate-spin" />}
                      新建草稿骨架并重新抽取
                    </Button>
                  ) : extractionJob?.status === 'failed' || extractionStale ? (
                    <Button
                      className="mt-3 w-full bg-[#B00055] hover:bg-[#8F0046]"
                      disabled={building}
                      onClick={() => void retryExtraction()}
                    >
                      {building && <LoaderCircle className="mr-2 size-4 animate-spin" />}
                      恢复知识抽取
                    </Button>
                  ) : (
                    <Button
                      className="mt-3 w-full bg-[#B00055] hover:bg-[#8F0046]"
                      disabled={
                        building ||
                        extractionJob?.status === 'queued' ||
                        extractionJob?.status === 'running'
                      }
                      onClick={() => void extract()}
                    >
                      {(building ||
                        extractionJob?.status === 'queued' ||
                        extractionJob?.status === 'running') && (
                        <LoaderCircle className="mr-2 size-4 animate-spin" />
                      )}
                      抽取知识点与课时关系
                    </Button>
                  )}
                </div>
                <div className="rounded-2xl border bg-gradient-to-b from-white to-rose-50/40 p-3">
                  <div className="mb-3 flex items-center gap-2 text-xs font-medium">
                    <Network className="size-3.5 text-[#B00055]" />
                    图谱骨架
                  </div>
                  <div className="flex flex-col items-center text-[10px]">
                    <div className="max-w-full truncate rounded-lg bg-[#B00055] px-3 py-2 font-medium text-white">
                      {course.title}
                    </div>
                    <div className="h-4 w-px bg-rose-300" />
                    <div className="grid w-full grid-cols-3 gap-2">
                      {course.modules.slice(0, 3).map((module) => (
                        <div key={module.id} className="min-w-0 text-center">
                          <div className="truncate rounded-lg border border-rose-200 bg-white px-2 py-2 font-medium text-[#8F0046]">
                            {module.title}
                          </div>
                          <div className="mx-auto h-3 w-px bg-slate-300" />
                          <div className="rounded-lg bg-slate-100 px-1.5 py-2 text-slate-600">
                            {module.lessons.length} 课时
                          </div>
                        </div>
                      ))}
                    </div>
                    <div className="mt-3 flex w-full items-center justify-center gap-2 rounded-lg border border-dashed border-rose-200 bg-white/70 px-2 py-2 text-slate-500">
                      <span>{counts.knowledge} 个知识点</span><span>→</span>
                      <span>{counts.objectives} 个学习目标</span><span>→</span>
                      <span>{counts.evidence} 条证据</span>
                    </div>
                    <div className="mt-3 w-full border-t border-rose-100 pt-3">
                      <p className="mb-2 text-left text-[9px] text-slate-400">代表性知识节点</p>
                      <div className="flex flex-wrap gap-1.5">
                        {graph.nodes
                          .filter((node) => node.type === 'knowledge-point')
                          .slice(0, 6)
                          .map((node) => (
                            <span
                              key={node.id}
                              title={node.description}
                              className="max-w-full truncate rounded-full border border-rose-200 bg-white px-2 py-1 text-[9px] text-[#8F0046]"
                            >
                              {node.title}
                            </span>
                          ))}
                      </div>
                    </div>
                  </div>
                </div>
              </>
            ) : (
              <div className="rounded-2xl border border-dashed p-5 text-center">
                <Network className="mx-auto size-8 text-[#B00055]/45" />
                <h4 className="mt-3 text-sm font-semibold">尚未建立课程知识图谱</h4>
                <p className="mt-2 text-xs leading-5 text-muted-foreground">
                  先把课程结构和已解析材料写入标准图谱，再进行知识点抽取与教师审核。
                </p>
                <Button
                  className="mt-4 w-full bg-[#B00055] hover:bg-[#8F0046]"
                  disabled={!databaseConfigured || building}
                  onClick={() => void bootstrap()}
                >
                  {building && <LoaderCircle className="mr-2 size-4 animate-spin" />}建立图谱骨架
                </Button>
                {!databaseConfigured && (
                  <p className="mt-2 text-[10px] text-amber-700">需要配置 COURSE_DATABASE_URL</p>
                )}
              </div>
            )}
            {error && <p className="rounded-xl bg-red-50 p-3 text-xs text-red-700">{error}</p>}
          </div>
        ) : (
          <div className="space-y-3">
            {artifacts.length ? (
              artifacts.map((artifact) => (
                <button
                  key={artifact.id}
                  onClick={() => router.push(`/course-space/${course.id}/review/${artifact.id}`)}
                  className="group w-full overflow-hidden rounded-2xl border bg-white text-left transition hover:border-[#B00055]/30 hover:shadow-md"
                >
                  <div className="relative h-28 overflow-hidden border-b bg-slate-50">
                    <div
                      className="absolute inset-0 origin-top-left scale-[.28] overflow-hidden p-6 opacity-80"
                      style={{ width: '357%', height: '357%' }}
                      dangerouslySetInnerHTML={{
                        __html: artifact.htmlContent || `<h1>${artifact.title}</h1>`,
                      }}
                    />
                    <span className="absolute right-2 top-2 rounded-full bg-white/90 px-2 py-1 text-[9px] shadow-sm">
                      {artifact.status}
                    </span>
                  </div>
                  <div className="p-3">
                    <div className="flex items-center gap-2">
                      <FileText className="size-4 shrink-0 text-[#B00055]" />
                      <span className="line-clamp-1 text-xs font-semibold">{artifact.title}</span>
                    </div>
                    <div className="mt-2 flex items-center justify-between text-[10px] text-muted-foreground">
                      <span>{artifact.citations.length} 条来源引用</span>
                      <ExternalLink className="size-3 opacity-0 group-hover:opacity-100" />
                    </div>
                  </div>
                </button>
              ))
            ) : (
              <div className="rounded-2xl border border-dashed p-6 text-center text-xs text-muted-foreground">
                <BookOpenCheck className="mx-auto mb-3 size-8 opacity-40" />
                生成并审核后的大纲、计划、课件、讲稿和习题会保存在这里。
              </div>
            )}
          </div>
        )}
      </div>
    </aside>
  );
}
