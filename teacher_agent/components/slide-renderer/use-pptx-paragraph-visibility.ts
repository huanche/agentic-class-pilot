'use client';
import { useLayoutEffect, type RefObject } from 'react';
import { useCanvasStore } from '@/lib/store/canvas';
import { pptxBackgroundKey, pptxParagraphKey } from '@/lib/import/pptx-animations';

/** Keep layout space and paragraph numbering intact while native builds hide individual lines. */
export function usePptxParagraphVisibility(
  container: RefObject<HTMLDivElement | null>,
  slideId: string,
) {
  const hidden = useCanvasStore.use.hiddenElementIdList();
  useLayoutEffect(() => {
    const keys = new Set(hidden);
    for (const owner of container.current?.querySelectorAll<HTMLElement>(
      '.slide-element, .screen-element',
    ) ?? []) {
      const background = owner.querySelector<SVGElement>(
        '.base-element-shape > .rotate-wrapper > .element-content > svg',
      );
      if (background)
        background.style.visibility = keys.has(
          pptxBackgroundKey(owner.id.slice('screen-element-'.length)),
        )
          ? 'hidden'
          : '';
    }
    for (const paragraph of container.current?.querySelectorAll<HTMLElement>(
      '[data-pptx-paragraph]',
    ) ?? []) {
      const owner = paragraph.closest<HTMLElement>('.slide-element, .screen-element');
      if (!owner?.id.startsWith('screen-element-')) continue;
      const id = owner.id.slice('screen-element-'.length);
      const index = Number(paragraph.dataset.pptxParagraph);
      paragraph.style.visibility = keys.has(pptxParagraphKey(id, index)) ? 'hidden' : '';
    }
  }, [container, hidden, slideId]);
}
