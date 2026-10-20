import type { ImportedPptSlideDraft, PptContentDraft } from '@/lib/types/generation';

export function revisePptContent(
  draft: PptContentDraft,
  slides: ImportedPptSlideDraft[],
): PptContentDraft {
  return { ...draft, slides, revision: draft.revision + 1, updatedAt: Date.now() };
}

/** Migrate old, blank review drafts too; a saved empty draft must not bypass OCR. */
export function needsPptImageOcr(slide: ImportedPptSlideDraft) {
  return (
    slide.imageOcr === 'pending' ||
    (!slide.imageOcr &&
      !slide.content.trim() &&
      !slide.formulas?.length &&
      /^第\s*\d+\s*页$/.test(slide.title.trim()))
  );
}

export function mergePptOcrResult(
  draft: PptContentDraft,
  before: ImportedPptSlideDraft,
  result: { title: string; content: string },
): PptContentDraft {
  return {
    ...draft,
    revision: draft.revision + 1,
    updatedAt: Date.now(),
    slides: draft.slides.map((slide) =>
      slide.id !== before.id
        ? slide
        : {
            ...slide,
            // An in-flight OCR response must never overwrite a teacher's edits.
            title: slide.title === before.title ? result.title : slide.title,
            content: slide.content === before.content ? result.content : slide.content,
            imageOcr: 'complete',
          },
    ),
  };
}

export function pptOcrEndpoint(courseId: string, materialId: string, originalIndex: number) {
  return `/api/course-space/${encodeURIComponent(courseId)}/materials/${encodeURIComponent(materialId)}/ocr/${originalIndex + 1}`;
}
