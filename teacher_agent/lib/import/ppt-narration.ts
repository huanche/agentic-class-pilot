import type { Action } from '@/lib/types/action';
import { focusSpeechIndex } from '@/lib/choreography/timeline';
import type { PPTElement } from '@openmaic/dsl';
import type { PptContentDraft } from '@/lib/types/generation';
import { HIGH_FIDELITY_COURSEWARE_POLICY } from '@/lib/import/high-fidelity-courseware-policy';

export const MAX_PPT_NARRATION_CHARS = HIGH_FIDELITY_COURSEWARE_POLICY.narration.regularMaxChars;
export const MAX_FORMULA_NARRATION_CHARS =
  HIGH_FIDELITY_COURSEWARE_POLICY.narration.formulaMaxChars;
export const FORMULA_NARRATION_MARKER = '【公式增强页面】';

function compact(value: string): string {
  return value.replace(/\s+/g, ' ').trim();
}

export function shortenPptNarration(
  value: string,
  maxChars: number = MAX_PPT_NARRATION_CHARS,
): string {
  const text = compact(value);
  if (text.length <= maxChars) return text;
  const candidate = text.slice(0, maxChars);
  const lastBoundary = Math.max(
    candidate.lastIndexOf('。'),
    candidate.lastIndexOf('！'),
    candidate.lastIndexOf('？'),
    candidate.lastIndexOf('. '),
  );
  return `${candidate.slice(0, lastBoundary >= maxChars * 0.55 ? lastBoundary + 1 : maxChars).trim()}……`;
}

export function buildPptNarrationScripts(draft?: PptContentDraft): string[] {
  if (!draft) return [];
  return draft.slides
    .filter((slide) => slide.include)
    .map((slide) => {
      const notes = compact(slide.speakerNotes);
      const body = compact(slide.content);
      const teacherComment = compact(slide.teacherComment || '');
      const formulas = slide.formulas?.filter(Boolean) ?? [];
      return [
        formulas.length ? FORMULA_NARRATION_MARKER : '',
        `本页标题：${slide.title || `第 ${slide.originalIndex + 1} 页`}`,
        body ? `页面可见内容：${body}` : '',
        notes ? `教师原始讲稿：${notes}` : '',
        formulas.length ? `本页公式（LaTeX）：${formulas.join('；')}` : '',
        formulas.length
          ? '讲解要求：覆盖本页主要文字和结论。不要逐字符、逐运算符朗读公式；先说明公式解决什么问题，再逐项解释关键物理量、上下标、系数或积分区间的物理意义，最后概括各项之间的整体关系和本页用途。公式较长时只介绍每一项的物理意义，不念 LaTeX 源码。'
          : '',
        teacherComment ? `教师修订要求：${teacherComment}` : '',
      ]
        .filter(Boolean)
        .join('\n');
    });
}

/** Preserve authored bindings; semantic review runs after narration processing. */
export function alignFocusActionsToSpeech(actions: Action[], _elements: PPTElement[]): Action[] {
  return actions.filter(
    (action, index) =>
      (action.type !== 'spotlight' && action.type !== 'laser') ||
      actions[focusSpeechIndex(actions, index)]?.type === 'speech',
  );
}

export function alignActionsToPptNarration(
  actions: Action[],
  narrationScript?: string,
  elements: PPTElement[] = [],
  options: { preserveGeneratedLength?: boolean } = {},
): Action[] {
  const formulaPage = narrationScript?.includes(FORMULA_NARRATION_MARKER) === true;
  const maxChars = formulaPage ? MAX_FORMULA_NARRATION_CHARS : MAX_PPT_NARRATION_CHARS;
  if (actions.some((action) => action.type === 'speech' && action.text)) {
    // The model paired these paragraphs with visual cues. Concatenating and
    // evenly re-splitting moves sentences across cues (and splits python.org).
    // Legacy length limits may shorten a paragraph in its own slot, never move
    // its sentences under a different target. Budgeted courses keep all text.
    let remaining = options.preserveGeneratedLength ? Infinity : maxChars;
    const aligned: Action[] = [];
    for (const action of actions) {
      if (action.type !== 'speech') {
        aligned.push(action);
        continue;
      }
      if (remaining <= 0) continue;
      const text =
        action.text.length <= remaining
          ? action.text
          : remaining > 2
            ? shortenPptNarration(action.text, remaining - 2)
            : '';
      if (!text) continue;
      remaining -= text.length;
      aligned.push({ ...action, text, audioId: undefined, audioInvalidated: true });
    }
    return elements.length ? alignFocusActionsToSpeech(aligned, elements) : aligned;
  }
  const script = shortenPptNarration(narrationScript || '', maxChars);
  if (!script) return actions;
  return [{ id: `ppt-narration-${Date.now()}`, type: 'speech', text: script }, ...actions];
}
