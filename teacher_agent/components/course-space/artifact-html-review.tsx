'use client';

import { useState } from 'react';
import { Download, Eye, Pencil } from 'lucide-react';
import { Button } from '@/components/ui/button';
import type { CourseArtifactRecord } from '@/lib/course-space';

export function ArtifactHtmlReview({
  artifact,
  onChange,
  fullScreen = false,
  readOnly = false,
}: {
  artifact: CourseArtifactRecord;
  onChange: (content: string) => void;
  fullScreen?: boolean;
  readOnly?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  return <div className={`overflow-hidden border bg-white ${fullScreen ? 'flex min-h-0 flex-1 flex-col rounded-2xl shadow-sm' : 'rounded-lg'}`}>
    <div className="flex items-center justify-between border-b bg-slate-50 px-3 py-2">
      <span className="text-xs font-medium text-slate-600">{editing ? 'Markdown 编辑' : 'HTML 预览'}</span>
      <div className="flex gap-2">
        {artifact.wordStorageKey && <Button size="sm" variant="outline" asChild>
          <a href={`/api/course-space/${artifact.courseId}/artifacts/${artifact.id}/word`} download>
            <Download className="mr-1 size-3" />下载 Word
          </a>
        </Button>}
        {!readOnly && <Button size="sm" variant="outline" onClick={() => setEditing((value) => !value)}>
          {editing ? <><Eye className="mr-1 size-3" />查看预览</> : <><Pencil className="mr-1 size-3" />编辑内容</>}
        </Button>}
      </div>
    </div>
    {editing ? <textarea
      className="min-h-96 w-full resize-y border-0 p-4 font-mono text-sm outline-none"
      value={artifact.content}
      onChange={(event) => onChange(event.target.value)}
    /> : <article
      className={`artifact-document min-h-96 overflow-auto text-[15px] leading-7 text-slate-800 [&_h1]:mb-5 [&_h1]:text-2xl [&_h1]:font-bold [&_h2]:mb-3 [&_h2]:mt-7 [&_h2]:text-xl [&_h2]:font-semibold [&_h3]:mb-2 [&_h3]:mt-5 [&_h3]:text-lg [&_h3]:font-semibold [&_li]:ml-6 [&_li]:list-disc [&_ol_li]:list-decimal [&_p]:my-2 [&_blockquote]:my-4 [&_blockquote]:border-l-4 [&_blockquote]:border-blue-300 [&_blockquote]:bg-blue-50 [&_blockquote]:px-4 [&_blockquote]:py-2 [&_.source-citation]:rounded [&_.source-citation]:bg-amber-50 [&_.source-citation]:px-1 [&_.source-citation]:text-xs [&_.source-citation]:text-amber-700 ${fullScreen ? 'min-h-0 flex-1 px-8 py-7 lg:px-14 lg:py-10' : 'max-h-[680px] p-6'}`}
      dangerouslySetInnerHTML={{ __html: artifact.htmlContent || '<p>暂无可预览内容，请保存后刷新。</p>' }}
    />}
  </div>;
}
