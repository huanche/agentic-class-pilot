'use client';

import { FileCode2, FileText, Presentation, ExternalLink } from 'lucide-react';
import { useRouter } from 'next/navigation';
import type { CourseArtifactRecord } from '@/lib/course-space';

const typeNames: Record<string, string> = {
  'course-outline': '教学大纲', 'module-plan': '教学计划', 'lesson-courseware': '互动课件',
  narration: '讲稿与配音', 'exercise-set': '习题与答案',
  'assessment-rubric': '测验与量规', 'pbl-project': 'PBL 项目',
};

export function ArtifactGallery({ courseId, artifacts, compact = false }: {
  courseId: string; artifacts: CourseArtifactRecord[]; compact?: boolean;
}) {
  const router = useRouter();
  if (artifacts.length === 0) return <div className="rounded-xl border border-dashed bg-white/60 p-10 text-center text-sm text-muted-foreground">尚未生成教学产物。完成生成后，大纲、计划、习题和互动课件会集中展示在这里。</div>;
  return <div className={`grid gap-5 ${compact ? 'grid-cols-2 xl:grid-cols-4' : 'grid-cols-1 md:grid-cols-2 xl:grid-cols-3'}`}>
    {artifacts.map((artifact) => <button key={artifact.id} onClick={() => router.push(`/course-space/${courseId}/review/${artifact.id}`)} className="group overflow-hidden rounded-2xl border bg-white text-left shadow-sm transition hover:-translate-y-1 hover:border-violet-300 hover:shadow-lg">
      <div className={`relative overflow-hidden border-b bg-gradient-to-br from-slate-50 via-white to-violet-50 ${compact ? 'h-36' : 'h-48'}`}>
        <div className="absolute inset-0 origin-top-left scale-[.48] overflow-hidden p-7 text-slate-700 opacity-90" style={{ width: '208%', height: '208%' }} dangerouslySetInnerHTML={{ __html: artifact.htmlContent || `<h1>${artifact.title}</h1><p>HTML 教学产物</p>` }}/>
        <div className="absolute left-4 top-4 rounded-lg bg-white/90 p-2 shadow-sm">{artifact.classroomUrl ? <Presentation className="size-5 text-violet-600"/> : artifact.wordStorageKey ? <FileText className="size-5 text-blue-600"/> : <FileCode2 className="size-5 text-emerald-600"/>}</div>
        <div className="absolute right-4 top-4 rounded-full bg-white/90 px-2.5 py-1 text-[11px] shadow-sm">{artifact.status}</div>
      </div>
      <div className="p-4"><div className="line-clamp-1 font-semibold">{artifact.title}</div><div className="mt-2 flex items-center justify-between text-xs text-muted-foreground"><span>{typeNames[artifact.type] || artifact.type} · HTML{artifact.wordStorageKey ? ' + Word' : ''}</span><span className="flex items-center gap-1 text-violet-600 opacity-0 transition group-hover:opacity-100">查看<ExternalLink className="size-3"/></span></div><div className="mt-2 text-xs text-muted-foreground">来源引用 {artifact.citations.length} 条 · {new Date(artifact.updatedAt).toLocaleDateString('zh-CN')}</div></div>
    </button>)}
  </div>;
}
