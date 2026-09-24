import type { PPTElement, Slide } from '@openmaic/dsl';
import { HIGH_FIDELITY_COURSEWARE_POLICY } from '@/lib/import/high-fidelity-courseware-policy';

const { bottomPadding, overflowTolerance, maxReasonableBottomFactor } =
  HIGH_FIDELITY_COURSEWARE_POLICY.viewport;

function elementBottom(element: PPTElement): number | null {
  if (element.type === 'line') return null;
  const rect = element as PPTElement & {
    top?: number;
    height?: number;
  };
  if (!Number.isFinite(rect.top) || !Number.isFinite(rect.height)) return null;
  return Number(rect.top) + Math.max(0, Number(rect.height));
}

/**
 * Expand only the playback viewport when an element visibly crosses the source
 * slide's bottom edge. Fully off-canvas animation assets and implausibly large
 * bounds are ignored. The renderer then fits the taller page into its host,
 * showing all intended content without mutating persisted PPT geometry.
 */
export function withContentAwareViewport(slide: Slide): Slide {
  const width = slide.viewportSize;
  const sourceHeight = width * slide.viewportRatio;
  let requiredHeight = sourceHeight;

  for (const element of slide.elements) {
    const top = 'top' in element && Number.isFinite(element.top) ? element.top : null;
    const bottom = elementBottom(element);
    if (top === null || bottom === null) continue;
    if (top < 0 || top >= sourceHeight) continue;
    if (bottom > sourceHeight * maxReasonableBottomFactor) continue;
    if (bottom > sourceHeight + overflowTolerance) {
      requiredHeight = Math.max(requiredHeight, bottom + bottomPadding);
    }
  }

  if (requiredHeight === sourceHeight) return slide;
  return { ...slide, viewportRatio: requiredHeight / width };
}
