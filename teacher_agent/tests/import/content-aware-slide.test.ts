import { describe, expect, it } from 'vitest';
import type { Slide } from '@openmaic/dsl';
import { withContentAwareViewport } from '@/lib/import/content-aware-slide';

function makeSlide(elements: Slide['elements']): Slide {
  return {
    id: 'slide',
    viewportSize: 1000,
    viewportRatio: 0.75,
    theme: { backgroundColor: '#fff', themeColors: [], fontColor: '#000', fontName: 'Arial' },
    elements,
  };
}

describe('content-aware playback viewport', () => {
  it('expands the page for a visible element crossing the bottom edge', () => {
    const slide = makeSlide([
      { id: 'image', type: 'image', left: 50, top: 680, width: 400, height: 140, src: 'x' },
    ] as Slide['elements']);

    const fitted = withContentAwareViewport(slide);

    expect(fitted).not.toBe(slide);
    expect(fitted.viewportSize * fitted.viewportRatio).toBe(832);
  });

  it('keeps a normal page unchanged', () => {
    const slide = makeSlide([
      { id: 'text', type: 'text', left: 50, top: 100, width: 400, height: 100, content: 'x' },
    ] as Slide['elements']);

    expect(withContentAwareViewport(slide)).toBe(slide);
  });

  it('ignores fully off-canvas animation assets and implausible bounds', () => {
    const slide = makeSlide([
      { id: 'off', type: 'image', left: 0, top: 760, width: 200, height: 100, src: 'x' },
      { id: 'huge', type: 'image', left: 0, top: 700, width: 200, height: 1000, src: 'x' },
    ] as Slide['elements']);

    expect(withContentAwareViewport(slide)).toBe(slide);
  });
});
