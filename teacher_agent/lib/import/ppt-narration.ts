import type { Action } from '@/lib/types/action';
import type { PPTElement } from '@openmaic/dsl';
import type { PptContentDraft } from '@/lib/types/generation';
import { HIGH_FIDELITY_COURSEWARE_POLICY } from '@/lib/import/high-fidelity-courseware-policy';

export const MAX_PPT_NARRATION_CHARS =
  HIGH_FIDELITY_COURSEWARE_POLICY.narration.regularMaxChars;
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

function splitForSlots(script: string, slots: number): string[] {
  if (slots <= 1) return [script];
  const sentences = script
    .match(/[^。！？.!?]+[。！？.!?]?/g)
    ?.map(compact)
    .filter(Boolean) ?? [script];
  const chunks = Array.from({ length: Math.min(slots, sentences.length) }, () => '');
  sentences.forEach((sentence, index) => {
    const target = Math.min(
      chunks.length - 1,
      Math.floor((index * chunks.length) / sentences.length),
    );
    chunks[target] += sentence;
  });
  return chunks.map(compact).filter(Boolean);
}

/** Keep visual actions and constrain the model's explanation to one concise page narration. */
function elementTeachingText(element: PPTElement): string {
  const record = element as unknown as Record<string, unknown>;
  const values = [record.content, record.text, record.latex, record.alt, record.name];
  return compact(
    values
      .filter((value): value is string => typeof value === 'string')
      .join(' ')
      .replace(/<[^>]+>/g, ' '),
  );
}

function semanticTokens(value: string): Set<string> {
  const normalized = value.toLowerCase().replace(/<[^>]+>/g, ' ');
  const tokens = new Set(normalized.match(/[a-z0-9]{2,}|[\u3400-\u9fff]/g) ?? []);
  const chinese = [...normalized].filter((char) => /[\u3400-\u9fff]/u.test(char));
  for (let i = 0; i < chinese.length - 1; i++) tokens.add(chinese[i] + chinese[i + 1]);
  return tokens;
}

function overlapScore(left: string, right: string): number {
  const a = semanticTokens(left);
  const b = semanticTokens(right);
  let score = 0;
  for (const token of a) if (b.has(token)) score += token.length > 1 ? 2 : 1;
  return score;
}

/** Rebind each focus cue to the element actually described by its following speech. */
export function alignFocusActionsToSpeech(actions: Action[], elements: PPTElement[]): Action[] {
  const candidates = elements
    .map((element) => ({ id: element.id, text: elementTeachingText(element) }))
    .filter((item) => item.text.length > 0);
  const result: Action[] = [];
  for (let index = 0; index < actions.length; index++) {
    const action = actions[index];
    if (action.type !== 'spotlight' && action.type !== 'laser') {
      result.push(action);
      continue;
    }
    const speech = actions[index + 1];
    if (speech?.type !== 'speech') continue;
    const current = candidates.find((item) => item.id === action.elementId);
    if (current && overlapScore(current.text, speech.text) > 0) {
      result.push(action);
      continue;
    }
    const ranked = candidates
      .map((item) => ({ ...item, score: overlapScore(item.text, speech.text) }))
      .sort((a, b) => b.score - a.score);
    if (ranked[0]?.score > 0) result.push({ ...action, elementId: ranked[0].id });
  }
  return result;
}

export function alignActionsToPptNarration(
  actions: Action[],
  narrationScript?: string,
  elements: PPTElement[] = [],
): Action[] {
  const generatedSpeech = actions
    .filter((action) => action.type === 'speech')
    .map((action) => action.text)
    .join('');
  const formulaPage = narrationScript?.includes(FORMULA_NARRATION_MARKER) === true;
  const script = shortenPptNarration(
    generatedSpeech || narrationScript || '',
    formulaPage ? MAX_FORMULA_NARRATION_CHARS : MAX_PPT_NARRATION_CHARS,
  );
  if (!script) return actions;
  const speechCount = actions.filter((action) => action.type === 'speech').length;
  if (speechCount === 0) {
    return [
      { id: `ppt-narration-${Date.now()}`, type: 'speech', text: script },
      ...actions,
    ] as Action[];
  }
  const chunks = splitForSlots(script, speechCount);
  let speechIndex = 0;
  const aligned: Action[] = [];
  for (const action of actions) {
    if (action.type !== 'speech') {
      aligned.push(action);
      continue;
    }
    const text = chunks[speechIndex++];
    if (text) aligned.push({ ...action, text, audioId: undefined, audioInvalidated: true });
  }
  return elements.length > 0 ? alignFocusActionsToSpeech(aligned, elements) : aligned;
}
