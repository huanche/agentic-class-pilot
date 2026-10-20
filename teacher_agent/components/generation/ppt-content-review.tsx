'use client';

import { useState } from 'react';
import { Check, Eye, FileText, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import type { PptContentDraft } from '@/lib/types/generation';
import { needsPptImageOcr, pptOcrEndpoint, revisePptContent } from '@/lib/import/ppt-content-ocr';
import { usePptContentOcr, type PptOcrSource } from './use-ppt-content-ocr';

interface PptContentReviewProps {
  draft: PptContentDraft;
  onChange: (draft: PptContentDraft) => void;
  onConfirm: () => void;
  onBack: () => void;
  source?: PptOcrSource;
}

export function PptContentReview({
  draft,
  onChange,
  onConfirm,
  onBack,
  source,
}: PptContentReviewProps) {
  const ocr = usePptContentOcr(draft, onChange, source);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const selected = draft.slides[selectedIndex];
  const includedCount = draft.slides.filter((slide) => slide.include).length;
  const pendingCount = draft.slides.filter(
    (slide) => slide.include && needsPptImageOcr(slide),
  ).length;
  const imageCount = draft.slides.filter(
    (slide) => slide.include && (slide.imageOcr === 'complete' || needsPptImageOcr(slide)),
  ).length;

  const updateSelected = (updates: Partial<NonNullable<typeof selected>>) => {
    if (!selected) return;
    const slides = draft.slides.map((slide, index) =>
      index === selectedIndex ? { ...slide, ...updates } : slide,
    );
    ocr.update(revisePptContent(draft, slides));
  };

  const toggleIncluded = (index: number, include: boolean) => {
    const slides = draft.slides.map((slide, itemIndex) =>
      itemIndex === index ? { ...slide, include } : slide,
    );
    ocr.update(revisePptContent(draft, slides));
  };

  return (
    <div className="min-h-[100dvh] w-full bg-gradient-to-b from-slate-50 to-slate-100 p-4 dark:from-slate-950 dark:to-slate-900">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-5 pt-8">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="mb-2 flex items-center gap-2 text-xs font-medium uppercase tracking-[0.2em] text-blue-500">
              <Eye className="size-4" />
              PPT 内容审核
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

        {imageCount > 0 && (
          <div
            className="space-y-2 rounded-xl border bg-white p-4 text-sm dark:bg-slate-900"
            role="status"
          >
            <div className="flex flex-wrap items-center justify-between gap-3">
              <span className="flex items-center gap-2">
                {ocr.running && <Loader2 className="size-4 animate-spin" />}
                {pendingCount
                  ? `图片文字识别：已完成 ${imageCount - pendingCount} / ${imageCount} 页`
                  : `图片文字识别完成：${imageCount} 页`}
              </span>
              {pendingCount > 0 && source?.materialId && (
                <div className="flex gap-2">
                  {ocr.running || ocr.paused ? (
                    <Button size="sm" variant="outline" onClick={ocr.togglePaused}>
                      {ocr.paused ? '继续识别' : '暂停识别'}
                    </Button>
                  ) : (
                    <Button size="sm" variant="outline" onClick={ocr.retry}>
                      重试未完成页面
                    </Button>
                  )}
                </div>
              )}
            </div>
            <progress
              className="h-2 w-full accent-blue-500"
              value={imageCount - pendingCount}
              max={imageCount}
              aria-label="图片文字识别进度"
            />
            {pendingCount > 0 && (
              <p className="text-muted-foreground">
                {!source?.materialId
                  ? '缺少原始材料，请返回课程重新选择此 PPT。'
                  : ocr.paused
                    ? '识别已暂停，已完成的内容会保留。'
                    : '原文件是图片页，正在识别其中的文字和公式。你可以先核对已完成的页面。'}
              </p>
            )}
          </div>
        )}

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
                    {needsPptImageOcr(slide) && (
                      <span className="shrink-0 text-xs text-muted-foreground">
                        {ocr.errors[slide.id] ? '失败' : '待识别'}
                      </span>
                    )}
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

              {(selected.imageOcr === 'complete' || needsPptImageOcr(selected)) &&
                source?.materialId && (
                  <details className="rounded-lg border p-3 text-sm" open>
                    <summary className="cursor-pointer font-medium">原始页面</summary>
                    {/* The source is an authenticated local API, never an arbitrary remote URL. */}
                    <img
                      className="mt-3 max-h-72 w-full object-contain"
                      src={pptOcrEndpoint(
                        source.courseId,
                        source.materialId,
                        selected.originalIndex,
                      )}
                      alt={`原 PPT 第 ${selected.originalIndex + 1} 页`}
                    />
                  </details>
                )}
              {needsPptImageOcr(selected) && (
                <div className="rounded-lg bg-blue-50 p-3 text-sm text-blue-900 dark:bg-blue-950 dark:text-blue-100">
                  {ocr.errors[selected.id] ||
                    (ocr.paused
                      ? '此页尚未完成识别。'
                      : '此页是图片，文字识别完成后会自动填入下方。')}
                  {ocr.errors[selected.id] && !ocr.running && (
                    <Button className="ml-3" size="sm" variant="outline" onClick={ocr.retry}>
                      重试
                    </Button>
                  )}
                </div>
              )}

              <label className="block space-y-2 text-sm font-medium">
                页面标题
                <Input
                  value={selected.title}
                  onChange={(event) => updateSelected({ title: event.target.value })}
                />
              </label>
              <label className="block space-y-2 text-sm font-medium">
                抽取到的正文
                <Textarea
                  className="min-h-40"
                  value={selected.content}
                  onChange={(event) => updateSelected({ content: event.target.value })}
                />
              </label>
              <label className="block space-y-2 text-sm font-medium">
                演讲者备注
                <Textarea
                  className="min-h-32"
                  value={selected.speakerNotes}
                  onChange={(event) => updateSelected({ speakerNotes: event.target.value })}
                  placeholder="可补充教师希望 AI 讲解的重点"
                />
              </label>
              <label className="block space-y-2 text-sm font-medium">
                教师修订意见
                <Textarea
                  value={selected.teacherComment || ''}
                  onChange={(event) => updateSelected({ teacherComment: event.target.value })}
                  placeholder="例如：增加一个工程案例，避免只读文字"
                />
              </label>

              <div className="flex flex-wrap justify-between gap-3 border-t pt-5">
                <Button variant="outline" onClick={onBack}>
                  返回
                </Button>
                <Button onClick={onConfirm} disabled={includedCount === 0 || pendingCount > 0}>
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
