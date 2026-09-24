'use client';

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { PPTLatexElement } from '@openmaic/dsl';

export interface BaseLatexElementProps {
  elementInfo: PPTLatexElement;
}

/**
 * Base latex element for read-only/playback mode.
 * Renders KaTeX HTML if available, falls back to legacy SVG path.
 */
export function BaseLatexElement({ elementInfo }: BaseLatexElementProps) {
  return (
    <div
      className="base-element-latex absolute"
      style={{
        top: `${elementInfo.top}px`,
        left: `${elementInfo.left}px`,
        width: `${elementInfo.width}px`,
        height: `${elementInfo.height}px`,
      }}
    >
      <div
        className="rotate-wrapper w-full h-full"
        style={{ transform: `rotate(${elementInfo.rotate}deg)` }}
      >
        <div
          className="element-content relative w-full h-full"
          style={{ color: elementInfo.color }}
        >
          {elementInfo.html ? (
            <KatexContent
              html={elementInfo.html}
              width={elementInfo.width}
              height={elementInfo.height}
              align={elementInfo.align}
            />
          ) : elementInfo.path && elementInfo.viewBox ? (
            <svg
              overflow="visible"
              width={elementInfo.width}
              height={elementInfo.height}
              stroke={elementInfo.color}
              strokeWidth={elementInfo.strokeWidth}
              fill="none"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="transform-origin-[0_0] overflow-visible"
            >
              <g
                transform={`scale(${elementInfo.width / elementInfo.viewBox[0]}, ${
                  elementInfo.height / elementInfo.viewBox[1]
                }) translate(0,0) matrix(1,0,0,1,0,0)`}
              >
                <path d={elementInfo.path} />
              </g>
            </svg>
          ) : null}
        </div>
      </div>
    </div>
  );
}

const ALIGN_MAP = {
  left: 'flex-start',
  center: 'center',
  right: 'flex-end',
} as const;

function KatexContent({
  html,
  width,
  height,
  align = 'center',
}: {
  html: string;
  width: number;
  height: number;
  align?: 'left' | 'center' | 'right';
}) {
  const innerRef = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);

  const measure = useCallback(() => {
    if (!innerRef.current) return;
    const naturalW = innerRef.current.scrollWidth;
    const naturalH = innerRef.current.scrollHeight;
    if (naturalW > 0 && naturalH > 0) {
      // Preserve the PPT formula's natural point size. Enlarging a short
      // equation to fill its OLE frame is what made imported formulas overlap
      // adjacent text; only shrink when the expression genuinely overflows.
      setScale(Math.min(width / naturalW, height / naturalH, 1));
    }
  }, [width, height]);

  useLayoutEffect(() => measure(), [measure, html]);

  useEffect(() => {
    const fonts = typeof document !== 'undefined' ? document.fonts : undefined;
    if (!fonts) return;
    let cancelled = false;
    fonts.ready.then(() => {
      if (!cancelled) measure();
    });
    const onLoadingDone = () => measure();
    fonts.addEventListener?.('loadingdone', onLoadingDone);
    return () => {
      cancelled = true;
      fonts.removeEventListener?.('loadingdone', onLoadingDone);
    };
  }, [measure, html]);

  const justify = ALIGN_MAP[align];
  const origin =
    align === 'left' ? 'left center' : align === 'right' ? 'right center' : 'center center';

  return (
    <div
      style={{
        width,
        height,
        overflow: 'hidden',
        display: 'flex',
        alignItems: 'center',
        justifyContent: justify,
      }}
    >
      <div
        ref={innerRef}
        className="[&_.katex-display]:!m-0"
        style={{
          transformOrigin: origin,
          transform: `scale(${scale})`,
          whiteSpace: 'nowrap',
        }}
        dangerouslySetInnerHTML={{ __html: html }}
      />
    </div>
  );
}
