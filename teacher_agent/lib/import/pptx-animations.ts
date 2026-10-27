import type { Action, PptxAnimationEffect, Slide } from '@openmaic/dsl';
import { pptxStepDurationMs } from '@/lib/choreography/timing';
export { pptxStepDurationMs } from '@/lib/choreography/timing';

export function pptxParagraphKey(id: string, paragraph: number): string {
  return `pptx-paragraph:${id}:${paragraph}`;
}

export function pptxBackgroundKey(id: string): string {
  return `pptx-background:${id}`;
}

export function pptxEffectTargetKeys(effect: PptxAnimationEffect): string[] {
  return effect.elementIds.flatMap((id) =>
    effect.paragraphRange
      ? Array.from(
          { length: effect.paragraphRange.end - effect.paragraphRange.start + 1 },
          (_, i) => pptxParagraphKey(id, effect.paragraphRange!.start + i),
        )
      : [effect.backgroundOnly ? pptxBackgroundKey(id) : id],
  );
}

/** Only entrance effects hide objects initially. An exit-only object must start visible. */
export function initialPlaybackHiddenElements(actions: readonly Action[]): string[] {
  const phases = new Map<string, 'in' | 'out'>();
  for (const action of actions) {
    if (action.type !== 'reveal') continue;
    if (action.pptxStep) {
      for (const effect of action.pptxStep.effects)
        if (effect.scope !== 'slide')
          for (const id of pptxEffectTargetKeys(effect))
            if (!phases.has(id)) phases.set(id, effect.phase);
    } else if (!phases.has(action.elementId)) phases.set(action.elementId, 'in');
  }
  return [...phases].filter(([, phase]) => phase === 'in').map(([id]) => id);
}

export function pptxAnimatedElementIds(slide: Slide): string[] {
  return [
    ...new Set(
      slide.pptxAnimation?.steps.flatMap((step) =>
        step.effects
          .filter((effect) => effect.scope !== 'slide')
          .flatMap((effect) => effect.elementIds),
      ) ?? [],
    ),
  ];
}

export function pptxAnimationNarrationContract(slide?: Slide): string {
  const steps = slide?.pptxAnimation?.steps;
  if (!steps?.length) return '';
  return `\n【原 PPT 动画顺序】\n${steps
    .map(
      (step, index) =>
        `${index + 1}. ${step.effects.map((effect) => `${effect.phase === 'in' ? '显示' : '移出'}对象 ${effect.elementIds.join(', ')}${effect.paragraphRange ? `，第 ${effect.paragraphRange.start + 1}–${effect.paragraphRange.end + 1} 段` : ''}`).join('；')}`,
    )
    .join(
      '\n',
    )}\n按以上顺序讲解对应对象，每次先让对象显示，再聚焦和讲解；对象退场前完成其讲解。每个入场步骤各安排一段讲解，同一文本框逐段出现时按段落顺序分别聚焦和讲解；此要求优先于通用的讲稿段数建议。只生成讲解和聚焦，不要另外生成这些对象的 reveal 动作，原动画由播放器保留。`;
}

/** Preserve original click order; bind clicks to narration boundaries, not guessed wall times. */
export function bindPptxAnimationsToActions(actions: Action[], slide?: Slide): Action[] {
  const steps = slide?.pptxAnimation?.steps;
  if (!steps?.length) return actions;
  const animated = new Set(pptxAnimatedElementIds(slide!));
  const base = actions.filter(
    (action) => action.type !== 'reveal' || (!action.pptxStep && !animated.has(action.elementId)),
  );
  const speeches = base.flatMap((action, index) => (action.type === 'speech' ? [index] : []));
  const insertions = new Map<number, Action[]>();
  let cursor = 0;
  for (const [index, step] of steps.entries()) {
    const entering = new Set(
      step.effects.filter((effect) => effect.phase === 'in').flatMap((effect) => effect.elementIds),
    );
    const exiting = new Set(
      step.effects
        .filter((effect) => effect.phase === 'out')
        .flatMap((effect) => effect.elementIds),
    );
    let position = step.trigger === 'auto' && index === 0 ? 0 : -1;
    if (position < 0 && entering.size) {
      position = base.findIndex(
        (action, i) =>
          i >= cursor &&
          (action.type === 'spotlight' || action.type === 'laser') &&
          entering.has(action.elementId),
      );
    }
    if (position < 0 && !entering.size && exiting.size) {
      for (let i = cursor; i < base.length; i++) {
        const action = base[i];
        if (
          (action.type === 'spotlight' || action.type === 'laser') &&
          exiting.has(action.elementId)
        ) {
          const speech = base.findIndex((candidate, j) => j >= i && candidate.type === 'speech');
          if (speech >= 0) position = speech + 1;
        }
      }
    }
    if (position < 0) {
      const speech =
        speeches[
          Math.min(speeches.length - 1, Math.floor((index * speeches.length) / steps.length))
        ];
      position = speech ?? base.length;
      // Keep focus cues immediately before their speech, behind the animation.
      while (position > 0 && ['spotlight', 'laser'].includes(base[position - 1].type)) position--;
    }
    position = Math.max(cursor, position);
    const followingSpeech = base.findIndex(
      (action, i) => i >= position && action.type === 'speech',
    );
    cursor = step.effects.some((effect) => effect.scope === 'slide')
      ? position
      : followingSpeech >= 0 && entering.size
        ? followingSpeech + 1
        : position;
    const native: Action = {
      id: `source-${step.id}`,
      type: 'reveal',
      elementId:
        step.effects[0].scope === 'slide'
          ? slide!.elements[0]?.id || slide!.id
          : step.effects[0].elementIds[0],
      duration: pptxStepDurationMs(step),
      pptxStep: step,
      title: '原 PPT 动画',
    };
    insertions.set(position, [...(insertions.get(position) ?? []), native]);
  }
  return base
    .flatMap((action, index) => [...(insertions.get(index) ?? []), action])
    .concat(insertions.get(base.length) ?? []);
}
