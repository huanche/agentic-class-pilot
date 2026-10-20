import { describe, expect, it } from 'vitest';
import { mergePptOcrResult, needsPptImageOcr } from '@/lib/import/ppt-content-ocr';
import type { ImportedPptSlideDraft, PptContentDraft } from '@/lib/types/generation';

const slide: ImportedPptSlideDraft = {
  id: 'page-1',
  originalIndex: 0,
  title: '第 1 页',
  content: '',
  speakerNotes: '',
  include: true,
};
describe('image-only PPT content review', () => {
  it('recovers previously saved blank drafts without treating real title-only pages as empty', () => {
    expect(needsPptImageOcr(slide)).toBe(true);
    expect(needsPptImageOcr({ ...slide, title: '课程目标' })).toBe(false);
    expect(needsPptImageOcr({ ...slide, formulas: ['x^2'] })).toBe(false);
    expect(needsPptImageOcr({ ...slide, imageOcr: 'complete' })).toBe(false);
    expect(needsPptImageOcr({ ...slide, imageOcr: 'not-needed' })).toBe(false);
  });
  it('merges parallel page results without losing teacher edits or inclusion choices', () => {
    const draft: PptContentDraft = {
      slides: [
        { ...slide, title: '老师标题', teacherComment: '保留公式', include: false },
        { ...slide, id: 'page-2', originalIndex: 1 },
      ],
      revision: 2,
      updatedAt: 1,
    };
    const first = mergePptOcrResult(draft, slide, { title: 'OCR 标题', content: '信号的分类' });
    const second = mergePptOcrResult(first, draft.slides[1], {
      title: '第二页',
      content: '随机信号',
    });
    expect(second.slides[0]).toMatchObject({
      title: '老师标题',
      content: '信号的分类',
      teacherComment: '保留公式',
      include: false,
      imageOcr: 'complete',
    });
    expect(second.slides[1]).toMatchObject({
      title: '第二页',
      content: '随机信号',
      imageOcr: 'complete',
    });
    expect(
      mergePptOcrResult({ ...draft, slides: [{ ...slide, content: '教师正文' }] }, slide, {
        title: '标题',
        content: 'OCR',
      }).slides[0].content,
    ).toBe('教师正文');
  });
});
