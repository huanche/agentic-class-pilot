import { renderQuizMathText, type QuizMathTextSegment } from './math-text';

export type QuizContentSegment =
  | QuizMathTextSegment
  | {
      type: 'code';
      value: string;
      block: boolean;
    };

/** Code is kept verbatim and never passed through the math or HTML renderer. */
export function renderQuizContent(text: string): QuizContentSegment[] {
  const segments: QuizContentSegment[] = [];
  const code = /```[^\r\n]*\r?\n([\s\S]*?)(?:```|$)|`([^`\r\n]+)`/g;
  let cursor = 0;
  for (const match of text.matchAll(code)) {
    if (match.index! > cursor)
      segments.push(...renderQuizMathText(text.slice(cursor, match.index)));
    segments.push({ type: 'code', value: match[1] ?? match[2], block: match[1] !== undefined });
    cursor = match.index! + match[0].length;
  }
  if (cursor < text.length) segments.push(...renderQuizMathText(text.slice(cursor)));
  return segments.length ? segments : [{ type: 'text', value: text }];
}
