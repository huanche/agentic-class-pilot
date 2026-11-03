import type { Scene } from '@/lib/types/stage';

export interface VideoCaption {
  start: number;
  end: number;
  text: string;
}
export interface ClipTiming {
  duration: number;
  speech: { actionId: string; offset: number; duration: number }[];
}

function captionPhrases(text: string): string[] {
  const words = Array.from(
    new Intl.Segmenter('zh', { granularity: 'word' }).segment(text),
    (v) => v.segment,
  );
  const parts: string[] = [];
  let part = '';
  for (const word of words) {
    if (Array.from(part + word).length > 32 && part.trim()) {
      parts.push(part.trim());
      part = '';
    }
    part += word;
    if (Array.from(part).length >= 18 && /[。！？!?；;]$/.test(part)) {
      parts.push(part.trim());
      part = '';
    }
  }
  if (part.trim()) parts.push(part.trim());
  return parts;
}

/** Use the recorder's exact speech offsets and measured audio durations. */
export function captionsForClip(scene: Scene, timing: ClipTiming): VideoCaption[] {
  const text = new Map(
    (scene.actions || []).flatMap((a) => (a.type === 'speech' ? [[a.id, a.text] as const] : [])),
  );
  if (!Number.isFinite(timing.duration) || timing.duration <= 0 || !Array.isArray(timing.speech))
    return [];
  return timing.speech
    .flatMap((s) => {
      if (!s || typeof s !== 'object') return [];
      const content = text.get(s.actionId)?.trim();
      if (!content || !Number.isFinite(s.offset) || !Number.isFinite(s.duration) || s.duration <= 0)
        return [];
      const start = Math.max(0, s.offset),
        end = Math.min(timing.duration, s.offset + s.duration);
      if (end <= start) return [];
      const parts = captionPhrases(content);
      const weight = (value: string) =>
        Array.from(value).reduce((sum, ch) => sum + (/[\x00-\x7f]/.test(ch) ? 0.55 : 1), 0);
      const weights = parts.map(weight),
        total = weights.reduce((sum, n) => sum + n, 0);
      let elapsed = 0;
      return parts.map((part, i) => {
        const cueStart = start + ((end - start) * elapsed) / total;
        elapsed += weights[i];
        return {
          start: cueStart,
          end: i === parts.length - 1 ? end : start + ((end - start) * elapsed) / total,
          text: part,
        };
      });
    })
    .sort((a, b) => a.start - b.start);
}

/** WebVTT cue text is markup; keep code such as `a < b` as literal text. */
export const captionCueText = (text: string) =>
  text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
