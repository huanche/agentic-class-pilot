'use client';

import { useState } from 'react';
import { Check, Eye, FileText } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import type { PptContentDraft } from '@/lib/types/generation';

interface PptContentReviewProps {
  draft: PptContentDraft;
  onChange: (draft: PptContentDraft) => void;
  onConfirm: () => void;
  onBack: () => void;
}

export function PptContentReview({ draft, onChange, onConfirm, onBack }: PptContentReviewProps) {
  const [selectedIndex, setSelectedIndex] = useState(0);
  const selected = draft.slides[selectedIndex];
  const includedCount = draft.slides.filter((slide) => slide.include).length;

  const updateSelected = (updates: Partial<NonNullable<typeof selected>>) => {
    if (!selected) return;
    const slides = draft.slides.map((slide, index) =>
      index === selectedIndex ? { ...slide, ...updates } : slide,
    );
    onChange({ ...draft, slides, revision: draft.revision + 1, updatedAt: Date.now() });
  };

  const toggleIncluded = (index: number, include: boolean) => {
    const slides = draft.slides.map((slide, itemIndex) =>
      itemIndex === index ? { ...slide, include } : slide,
    );
    onChange({ ...draft, slides, revision: draft.revision + 1, updatedAt: Date.now() });
  };

  return (
    <div className="min-h-[100dvh] w-full bg-gradient-to-b from-slate-50 to-slate-100 p-4 dark:from-slate-950 dark:to-slate-900">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-5 pt-8">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="mb-2 flex items-center gap-2 text-xs font-medium uppercase tracking-[0.2em] text-blue-500">
              <Eye className="size-4" />PPT 内容审核
            </div>
            <h1 className="text-2xl font-bold tracking-tight">先确认 AI 识别到的内容</h1>
            <p className="mt-2 text-sm text-muted-foreground">
              修改标题、正文和备注后，再生成教学大纲。未勾选的页面不会进入课堂。
            </p>
          </div>
          <div className="text-sm text-muted-foreground">
            保留 {includedCount} / {draft.slides.length} 页
          </div>
        </div>

        <div className="grid min-h-[560px] gap-5 lg:grid-cols-[260px_1fr]">
          <Card className="overflow-hidden p-2">
            <div className="max-h-[560px] space-y-1 overflow-y-auto">
              {draft.slides.map((slide, index) => (
                <div
                  key={slide.id}
                  className={`flex items-center gap-2 rounded-lg p-3 text-sm transition ${
                    selectedIndex === index
                      ? 'bg-blue-500/10 text-blue-700 dark:text-blue-300'
                      : 'hover:bg-muted/70'
                  } ${!slide.include ? 'opacity-50' : ''}`}
                >
                  <button
                    type="button"
                    onClick={() => setSelectedIndex(index)}
                    className="flex min-w-0 flex-1 items-center gap-2 text-left"
                  >
                    <FileText className="size-4 shrink-0" />
                    <span className="truncate">
                      {index + 1}. {slide.title || '未命名页面'}
                    </span>
                  </button>
                  <input
                    type="checkbox"
                    checked={slide.include}
                    onChange={(event) => toggleIncluded(index, event.target.checked)}
                    aria-label={`保留第 ${index + 1} 页`}
                  />
                </div>
              ))}
            </div>
          </Card>

          {selected && (
            <Card className="space-y-5 p-5 md:p-8">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-xs uppercase tracking-widest text-muted-foreground">
                    原始页码 {selected.originalIndex + 1}
                  </p>
                  <h2 className="mt-1 text-xl font-semibold">页面内容</h2>
                </div>
              </div>

              <label className="block space-y-2 text-sm font-medium">
                页面标题
                <Input value={selected.title} onChange={(event) => updateSelected({ title: event.target.value })} />
              </label>
              <label className="block space-y-2 text-sm font-medium">
                抽取到的正文
                <Textarea className="min-h-40" value={selected.content} onChange={(event) => updateSelected({ content: event.target.value })} />
              </label>
              <label className="block space-y-2 text-sm font-medium">
                演讲者备注
                <Textarea className="min-h-32" value={selected.speakerNotes} onChange={(event) => updateSelected({ speakerNotes: event.target.value })} placeholder="可补充教师希望 AI 讲解的重点" />
              </label>
              <label className="block space-y-2 text-sm font-medium">
                教师修订意见
                <Textarea value={selected.teacherComment || ''} onChange={(event) => updateSelected({ teacherComment: event.target.value })} placeholder="例如：增加一个工程案例，避免只读文字" />
              </label>

              <div className="flex flex-wrap justify-between gap-3 border-t pt-5">
                <Button variant="outline" onClick={onBack}>返回</Button>
                <Button onClick={onConfirm} disabled={includedCount === 0}>
                  <Check className="mr-2 size-4" />
                  确认内容并生成大纲
                </Button>
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
