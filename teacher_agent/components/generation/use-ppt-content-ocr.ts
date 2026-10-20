'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import type { PptContentDraft } from '@/lib/types/generation';
import { mergePptOcrResult, needsPptImageOcr, pptOcrEndpoint } from '@/lib/import/ppt-content-ocr';

export interface PptOcrSource {
  courseId: string;
  materialId?: string;
}

export function usePptContentOcr(
  draft: PptContentDraft,
  onChange: (draft: PptContentDraft) => void,
  source?: PptOcrSource,
) {
  const latest = useRef({ draft, onChange });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [running, setRunning] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [paused, setPaused] = useState(false);
  useEffect(() => {
    latest.current = { draft, onChange };
  }, [draft, onChange]);
  const update = useCallback((next: PptContentDraft) => {
    latest.current.draft = next;
    latest.current.onChange(next);
  }, []);
  const courseId = source?.courseId;
  const materialId = source?.materialId;
  const selection = draft.slides
    .filter((slide) => slide.include)
    .map((slide) => slide.id)
    .join(',');

  useEffect(() => {
    if (!courseId || !materialId || paused) return;
    const controller = new AbortController();
    const queue = latest.current.draft.slides.filter(
      (slide) => slide.include && needsPptImageOcr(slide),
    );
    if (!queue.length) return;
    let cursor = 0;
    setErrors({});
    setRunning(true);
    const worker = async () => {
      while (!controller.signal.aborted && cursor < queue.length) {
        const before = queue[cursor++];
        try {
          const response = await fetch(pptOcrEndpoint(courseId, materialId, before.originalIndex), {
            method: 'POST',
            signal: controller.signal,
          });
          const data = await response.json();
          if (!response.ok || !data.success || !data.result?.content?.trim()) {
            throw new Error(data.error || '未识别到文字，请重试');
          }
          if (controller.signal.aborted) return;
          update(mergePptOcrResult(latest.current.draft, before, data.result));
        } catch (error) {
          if (controller.signal.aborted) return;
          setErrors((previous) => ({
            ...previous,
            [before.id]: error instanceof Error ? error.message : '识别失败，请重试',
          }));
        }
      }
    };
    void Promise.all(Array.from({ length: Math.min(3, queue.length) }, worker)).finally(() => {
      if (!controller.signal.aborted) setRunning(false);
    });
    return () => {
      controller.abort();
      setRunning(false);
    };
  }, [courseId, materialId, selection, attempt, paused, update]);

  return {
    errors,
    running,
    paused,
    update,
    retry: () => {
      setPaused(false);
      setAttempt((value) => value + 1);
    },
    togglePaused: () => setPaused((value) => !value),
  };
}
