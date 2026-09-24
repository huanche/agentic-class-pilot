import { describe, expect, it } from 'vitest';
import type { Slide } from '@openmaic/dsl';
import {
  bindPptOutlinesToReviewedPages,
  buildImportedPptDraft,
  buildImportedPptOutlines,
  cleanImportedText,
  getImportedSlideTitle,
  resolveReviewedPptDraft,
  PPT_COURSEWARE_POLICY_VERSION,
} from '@/lib/import/pptx-course';

function slide(id: string, texts: string[], script?: string): Slide {
  return {
    id,
    viewportSize: 1000,
    viewportRatio: 16 / 9,
    theme: {
      backgroundColor: '#fff',
      themeColors: [],
      fontColor: '#000',
      fontName: 'Arial',
    },
    elements: texts.map((content, index) => ({
      id: `${id}-text-${index}`,
      type: 'text',
      content,
    })) as Slide['elements'],
    script,
  };
}

describe('high-fidelity PPTX course conversion', () => {
  it('keeps one outline per source slide in the original order', () => {
    const slides = [
      slide('a', ['<p>第一页标题</p>', '知识点 A'], '备注 A'),
      slide('b', ['第二页标题', '知识点 B']),
    ];

    const outlines = buildImportedPptOutlines(slides);

    expect(outlines).toHaveLength(slides.length);
    expect(outlines.map((outline) => outline.order)).toEqual([1, 2]);
    expect(outlines.map((outline) => outline.id)).toEqual(['pptx-slide-1', 'pptx-slide-2']);
    expect(outlines[0].description).toContain('保留该页原始视觉画布');
    expect(outlines[0].description).toContain('教师备注：备注 A');
    expect(outlines[0].description).toContain('激光笔');
  });

  it('extracts a readable title from imported rich text', () => {
    const imported = slide('a', ['<p><strong> 无线电波传播 </strong></p>']);
    expect(cleanImportedText('<p><strong> 无线电波传播 </strong></p>')).toBe('无线电波传播');
    expect(getImportedSlideTitle(imported, 0)).toBe('无线电波传播');
  });

  it('routes a semantic-formula page to OpenMAIC enhancement with exact LaTeX', () => {
    const formulaSlide = slide('formula', ['功率', '发射功率的定义']);
    formulaSlide.elements.push({
      id: 'eq-1',
      type: 'latex',
      latex: String.raw`P_{TX}=\frac{1}{T}\int|s(t)|^2dt`,
      html: '<span>formula</span>',
    } as Slide['elements'][number]);

    const draft = buildImportedPptDraft([formulaSlide]);
    const [outline] = buildImportedPptOutlines([formulaSlide]);

    expect(draft.slides[0].generationStrategy).toBe('ai-formula-enhanced');
    expect(draft.generationPolicyVersion).toBe(PPT_COURSEWARE_POLICY_VERSION);
    expect(draft.slides[0].formulas).toEqual([String.raw`P_{TX}=\frac{1}{T}\int|s(t)|^2dt`]);
    expect(outline.description).toContain('OpenMAIC 公式增强重构');
    expect(outline.description).toContain(String.raw`P_{TX}=\frac{1}{T}\int|s(t)|^2dt`);
    expect(outline.description).toContain('禁止与标题、正文、注释重叠');
  });

  it('uses the final outline review as the page-count and ordering contract', () => {
    const draft = {
      slides: ['一', '二', '三'].map((title, originalIndex) => ({
        id: `pptx-slide-${originalIndex + 1}`,
        originalIndex,
        title,
        content: title,
        speakerNotes: '',
        include: true,
      })),
      revision: 1,
      updatedAt: 1,
    };
    const initial = bindPptOutlinesToReviewedPages(
      draft.slides.map((item, index) => ({
        id: `generated-${index}`,
        type: 'slide' as const,
        title: item.title,
        description: '',
        keyPoints: [],
        order: index + 1,
      })),
      draft,
    );

    // Teacher removes page 2 and moves page 3 before page 1 in outline review.
    const reviewed = [initial[2], initial[0]].map((outline, index) => ({
      ...outline,
      order: index + 1,
    }));
    const resolved = resolveReviewedPptDraft(reviewed, draft);

    expect(resolved?.slides.map((item) => item.originalIndex)).toEqual([2, 0]);
    expect(resolved?.slides).toHaveLength(reviewed.length);
  });

  it('rejects a final outline with more pages than the reviewed PPT', () => {
    const draft = {
      slides: [
        {
          id: 'pptx-slide-1',
          originalIndex: 0,
          title: '一',
          content: '',
          speakerNotes: '',
          include: true,
        },
      ],
      revision: 1,
      updatedAt: 1,
    };
    const outlines = [1, 2].map((order) => ({
      id: `outline-${order}`,
      type: 'slide' as const,
      title: `${order}`,
      description: '',
      keyPoints: [],
      order,
    }));

    expect(resolveReviewedPptDraft(outlines, draft)).toBeNull();
  });
});
