'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { BookOpenCheck, ExternalLink, FileText, Presentation } from 'lucide-react';
import type { Slide } from '@openmaic/dsl';
import type { CourseArtifactRecord } from '@/lib/course-space';
import { SlideThumbnail } from '@/components/slide-renderer/SlideThumbnail';
import { getFirstSlideByStages, revokeThumbnailSlideMediaUrls } from '@/lib/utils/stage-storage';

export function CourseArtifactGallery({ courseId, artifacts, embedded = false }: { courseId: string; artifacts: CourseArtifactRecord[]; embedded?: boolean }) {
  const router = useRouter();
  const [covers, setCovers] = useState<Record<string, Slide>>({});
  const coversRef = useRef<Record<string, Slide>>({});
  const visibleArtifacts = artifacts.slice(0, 8);

  useEffect(() => {
    let active = true;
    const classroomIds = [...new Set(visibleArtifacts.flatMap((artifact) => artifact.classroomId ? [artifact.classroomId] : []))];
    void getFirstSlideByStages(classroomIds).then((next) => {
      if (!active) {
        revokeThumbnailSlideMediaUrls(next);
        return;
      }
      const previous = coversRef.current;
      coversRef.current = next;
      setCovers(next);
      window.setTimeout(() => revokeThumbnailSlideMediaUrls(previous), 0);
    }).catch(() => undefined);
    return () => { active = false; };
  }, [artifacts]);

  useEffect(() => () => revokeThumbnailSlideMediaUrls(coversRef.current), []);

  const openArtifact = (artifact: CourseArtifactRecord) => {
    router.push(artifact.classroomUrl || `/course-space/${courseId}/review/${artifact.id}`);
  };

  return <section className={embedded ? 'p-2' : 'rounded-[24px] border border-white/80 bg-white/80 p-5 shadow-sm backdrop-blur-xl'}>
    <div className="mb-4 flex items-end justify-between gap-4"><div><h3 className="text-lg font-semibold">历史教学产物</h3><p className="mt-1 text-xs text-muted-foreground">大纲、计划、课件、讲稿和习题集中保存在当前课程。</p></div><button className="text-xs font-medium text-[#B00055]" onClick={() => router.push(`/course-space/${courseId}/artifacts`)}>查看全部产物 →</button></div>
    {visibleArtifacts.length ? <div className="grid grid-cols-1 gap-x-4 gap-y-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">{visibleArtifacts.map((artifact) => {
      const cover = artifact.classroomId ? covers[artifact.classroomId] : undefined;
      return <button key={artifact.id} onClick={() => openArtifact(artifact)} className="group min-w-0 text-left">
        <div className="relative aspect-[16/9] w-full overflow-hidden rounded-xl border bg-slate-50 shadow-sm transition duration-200 group-hover:-translate-y-0.5 group-hover:border-[#B00055]/30 group-hover:shadow-md">
          {cover ? <SlideThumbnail slide={cover} viewportRatio={cover.viewportRatio ?? 0.5625}/> : <div aria-hidden="true" className="absolute inset-0 origin-top-left scale-[.3] overflow-hidden bg-white p-6 opacity-85" style={{width:'334%',height:'334%'}} dangerouslySetInnerHTML={{__html:artifact.htmlContent || `<h1>${artifact.title}</h1>`}}/>}
          <span className="absolute right-2 top-2 rounded-full bg-white/90 px-2 py-1 text-[9px] shadow-sm backdrop-blur">{artifact.status}</span>
          <span className="absolute bottom-2 left-2 flex size-7 items-center justify-center rounded-lg bg-white/90 text-[#B00055] shadow-sm backdrop-blur">{artifact.classroomUrl ? <Presentation className="size-4"/> : <FileText className="size-4"/>}</span>
        </div>
        <div className="mt-2 flex min-w-0 items-center gap-2 px-0.5"><span className="min-w-0 flex-1 truncate text-sm font-medium">{artifact.title}</span><ExternalLink className="size-3 shrink-0 text-[#B00055] opacity-0 transition group-hover:opacity-100"/></div>
        <div className="mt-1 px-0.5 text-[10px] text-muted-foreground">{artifact.classroomUrl ? '互动课件' : `${artifact.citations.length} 条来源引用`}</div>
      </button>;
    })}</div> : <div className="rounded-2xl border border-dashed p-8 text-center text-xs text-muted-foreground"><BookOpenCheck className="mx-auto mb-3 size-8 opacity-40"/>尚无历史产物。可以通过上方智能体快捷入口启动生成流程。</div>}
  </section>;
}
