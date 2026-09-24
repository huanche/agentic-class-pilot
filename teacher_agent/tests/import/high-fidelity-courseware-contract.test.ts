import { describe, expect, it } from 'vitest';
import type { Slide } from '@openmaic/dsl';
import { withContentAwareViewport } from '@/lib/import/content-aware-slide';
import { HIGH_FIDELITY_COURSEWARE_POLICY } from '@/lib/import/high-fidelity-courseware-policy';
import { buildPptNarrationScripts, FORMULA_NARRATION_MARKER } from '@/lib/import/ppt-narration';
import {
  buildImportedPptDraft,
  buildImportedPptOutlinesFromDraft,
  resolveReviewedPptDraft,
} from '@/lib/import/pptx-course';

function sourceSlide(id: string, title: string, formula?: string): Slide {
  const elements: Slide['elements'] = [
    { id: `${id}-title`, type: 'text', content: title, left: 40, top: 40, width: 500, height: 80 },
    { id: `${id}-body`, type: 'text', content: `${title}的核心内容`, left: 40, top: 150, width: 700, height: 100 },
  ] as Slide['elements'];
  if (formula) {
    elements.push({ id: `${id}-formula`, type: 'latex', latex: formula, html: '<span />' } as Slide['elements'][number]);
  }
  return {
    id,
    viewportSize: 1000,
    viewportRatio: 0.75,
    theme: { backgroundColor: '#fff', themeColors: [], fontColor: '#000', fontName: 'Arial' },
    elements,
    script: `讲解${title}`,
  };
}

describe('versioned high-fidelity courseware contract', () => {
  it('locks reviewed ordering, hybrid routing, narration coverage and playback geometry', () => {
    const formula = String.raw`P_{TX}=\frac{1}{T}\int|s(t)|^2dt`;
    const source = [
      sourceSlide('normal', '普通页面'),
      sourceSlide('formula', '公式页面', formula),
      sourceSlide('removed', '教师删除页面'),
    ];
    const draft = buildImportedPptDraft(source);

    expect(draft.generationPolicyVersion).toBe(HIGH_FIDELITY_COURSEWARE_POLICY.version);
    expect(draft.slides.map((page) => page.generationStrategy)).toEqual([
      'faithful',
      'ai-formula-enhanced',
      'faithful',
    ]);

    const initialOutlines = buildImportedPptOutlinesFromDraft(draft);
    const reviewedOutlines = [initialOutlines[1], initialOutlines[0]].map((outline, index) => ({
      ...outline,
      order: index + 1,
    }));
    const reviewedDraft = resolveReviewedPptDraft(reviewedOutlines, draft);

    expect(reviewedDraft).not.toBeNull();
    expect(reviewedDraft?.slides.map((page) => page.originalIndex)).toEqual([1, 0]);
    const scripts = buildPptNarrationScripts(reviewedDraft ?? undefined);
    expect(scripts).toHaveLength(reviewedOutlines.length);
    expect(scripts[0]).toContain(FORMULA_NARRATION_MARKER);
    expect(scripts[0]).toContain(formula);
    expect(scripts[1]).not.toContain(FORMULA_NARRATION_MARKER);

    const normalCanvas = source[0];
    expect(withContentAwareViewport(normalCanvas)).toBe(normalCanvas);
    const overflowingCanvas = {
      ...normalCanvas,
      elements: [
        ...normalCanvas.elements,
        { id: 'bottom', type: 'image', left: 0, top: 700, width: 300, height: 100, src: 'x' },
      ] as Slide['elements'],
    };
    expect(withContentAwareViewport(overflowingCanvas).viewportRatio).toBe(0.812);
  });
});
