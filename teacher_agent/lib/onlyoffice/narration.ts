import type { Action, Slide } from '@openmaic/dsl';
import type { NativePptxClick } from '@/lib/types/stage';

export const isNativeClick = (id: string) => id.startsWith('onlyoffice-click-');
export function nativePptxNarrationContract(clicks: NativePptxClick[]) {
  if (!clicks.length) return '';
  return `\n【原稿完整点击序列，由原 PPTX 读取】\n${clicks.map((click, i) => `${i + 1}. ${click.description}`).join('\n')}\n本页共有 ${clicks.length} 次点击。必须按顺序为每次点击各写至少一段独立的 speech 讲解，总 speech 段数不得少于 ${clicks.length}。讲解本次显示或移出的内容，原始动画交给 ONLYOFFICE 播放，不另造 reveal，不合并或漏掉点击步骤。`;
}

/** Bind the complete source clicks, while retaining supported old effects solely
 * for explicit legacy fallback. Unsupported source effects never disappear from
 * the native narration schedule just because the web importer cannot draw them.
 */
export function bindNativePptxActions(
  actions: Action[],
  slide: Slide,
  clicks: NativePptxClick[],
): Action[] {
  const base = actions.filter((a) => a.type !== 'reveal');
  const speeches = base.flatMap((a, i) => (a.type === 'speech' && a.text.trim() ? [i] : []));
  if (speeches.length < clicks.length) {
    throw Object.assign(
      new Error(
        `原稿有 ${clicks.length} 次点击，但只生成 ${speeches.length} 段讲解，请重试本页讲解。`,
      ),
      { errorCode: 'FOCUS_SPEECH_ALIGNMENT_FAILED' },
    );
  }
  const inserts = new Map<number, Action[]>();
  for (const [index, click] of clicks.entries()) {
    const position = speeches[Math.floor((index * speeches.length) / clicks.length)];
    const step = {
      id: click.id,
      trigger: 'click' as const,
      effects: [
        {
          elementIds: [slide.elements[0]?.id || slide.id],
          effect: 'appear' as const,
          phase: 'in' as const,
          delayMs: 0,
          durationMs: click.durationMs,
        },
      ],
    };
    const native: Action = {
      id: `source-${click.id}`,
      type: 'reveal',
      elementId: step.effects[0].elementIds[0],
      duration: click.durationMs,
      pptxStep: step,
      title: '原稿点击动画',
    };
    const legacy: Action[] = (slide.pptxAnimation?.steps ?? [])
      .filter((s) => click.sourceEffectIds.some((id) => s.id === `pptx-step-${id}`))
      .map((s) => ({
        id: `legacy-${s.id}`,
        type: 'reveal',
        elementId: s.effects[0].elementIds[0],
        pptxStep: s,
        title: '兼容动画',
      }));
    inserts.set(position, [native, ...legacy]);
  }
  return base.flatMap((action, index) => [...(inserts.get(index) ?? []), action]);
}
