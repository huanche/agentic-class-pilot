import type { PptxAnimationEffect, PptxAnimationTimeline } from '@openmaic/dsl';
import type { SafeXmlNode } from '../parser/XmlParser';

const PRESETS: Record<string, PptxAnimationEffect['effect']> = {
  '1': 'appear',
  '2': 'fly',
  '4': 'box',
  '10': 'fade',
  '22': 'wipe',
  '23': 'zoom',
};
const DIRECTIONS: Record<string, PptxAnimationEffect['direction']> = {
  '1': 'top',
  '2': 'right',
  '4': 'bottom',
  '8': 'left',
};
function descendants(node: SafeXmlNode, tag: string): SafeXmlNode[] {
  return node
    .allChildren()
    .flatMap((child) => [...(child.localName === tag ? [child] : []), ...descendants(child, tag)]);
}
function delay(node: SafeXmlNode): number {
  const condition = node.child('stCondLst').child('cond');
  const value = condition.numAttr('delay');
  return value != null && Number.isFinite(value) && value >= 0 ? value : 0;
}

/** Read PresentationML p:timing. Unknown effects stay visible and are reported, never guessed. */
export function parsePptxAnimations(root: SafeXmlNode): PptxAnimationTimeline | undefined {
  const timing = root.child('timing');
  if (!timing.exists()) return undefined;
  const timeline: PptxAnimationTimeline = { version: 1, steps: [], warnings: [] };
  const warn = (message: string) => {
    if (!timeline.warnings.includes(message)) timeline.warnings.push(message);
  };
  let lastStart = 0;
  let lastEnd = 0;
  const unsupportedTargets = new Set<string>();
  function visit(node: SafeXmlNode, parents: SafeXmlNode[]) {
    const presetClass = node.attr('presetClass');
    if (node.localName === 'cTn' && presetClass) {
      const id = node.attr('id') || String(timeline.steps.length + 1);
      const label = `动画 ${id}`;
      const targets = descendants(node, 'spTgt');
      const behavior = descendants(node, 'cBhvr');
      const animated = descendants(node, 'animEffect')[0];
      const filter = animated?.attr('filter') || '';
      const preset = node.attr('presetID') || '';
      // Some files serialize fade/wipe by filter, others only carry the Office preset.
      const effect =
        filter === 'fade'
          ? 'fade'
          : filter === 'box(out)'
            ? 'box'
            : /^wipe\((left|right|up|down)\)$/.test(filter)
              ? 'wipe'
              : !filter || filter === 'fly'
                ? PRESETS[preset]
                : undefined;
      const paragraph = targets[0]?.child('txEl').child('pRg');
      const paragraphRange = paragraph?.exists()
        ? { start: paragraph.numAttr('st') ?? -1, end: paragraph.numAttr('end') ?? -1 }
        : undefined;
      const unsupported =
        (presetClass !== 'entr' && presetClass !== 'exit') ||
        !effect ||
        !targets.length ||
        targets.some(
          (target) =>
            target.allChildren().length > 0 &&
            !target.child('bg').exists() &&
            !target.child('txEl').child('pRg').exists(),
        ) ||
        (paragraphRange &&
          (!Number.isSafeInteger(paragraphRange.start) ||
            !Number.isSafeInteger(paragraphRange.end) ||
            paragraphRange.start < 0 ||
            paragraphRange.end < paragraphRange.start ||
            paragraphRange.end > 10000)) ||
        descendants(node, 'animMotion').length > 0 ||
        parents.some((parent) => parent.attr('nodeType') === 'interactiveSeq') ||
        [node, ...descendants(node, 'cTn')].some(
          (n) =>
            n.attr('repeatCount') != null ||
            n.attr('repeatDur') != null ||
            n.attr('autoRev') === '1',
        );
      if (unsupported) {
        targets.forEach((target) => unsupportedTargets.add(target.attr('spid') || ''));
        warn(`${label}（${presetClass}/${preset || filter}）暂不支持；该对象保留静态显示。`);
        return;
      }
      const nodeType = node.attr('nodeType');
      const trigger =
        nodeType === 'withEffect' ? 'with' : nodeType === 'afterEffect' ? 'after' : 'click';
      // Non-root container delays are relative to the same click, not new click events.
      let mainIndex = -1;
      for (let i = 0; i < parents.length; i++)
        if (parents[i].attr('nodeType') === 'mainSeq') mainIndex = i;
      const containers = parents.slice(mainIndex + 1);
      const ownDelay =
        delay(node) +
        containers.filter((n) => n.localName === 'cTn').reduce((sum, n) => sum + delay(n), 0);
      if (trigger === 'click' || !timeline.steps.length) {
        timeline.steps.push({
          id: `pptx-step-${id}`,
          trigger: nodeType === 'afterEffect' || nodeType === 'withEffect' ? 'auto' : 'click',
          effects: [],
        });
        lastStart = 0;
        lastEnd = 0;
      }
      const start = (trigger === 'after' ? lastEnd : trigger === 'with' ? lastStart : 0) + ownDelay;
      const durations = behavior
        .map((n) => n.child('cTn').numAttr('dur'))
        .filter((n): n is number => n != null && Number.isFinite(n) && n >= 0);
      const durationMs = effect === 'appear' ? 1 : Math.max(1, ...durations);
      if (start + durationMs > 300000) {
        warn(`${label}超出可播放的动画时长，保留静态显示。`);
        return;
      }
      const filterDirection = /\((left|right|up|down)\)/.exec(filter)?.[1];
      const direction =
        filterDirection === 'up'
          ? 'top'
          : filterDirection === 'down'
            ? 'bottom'
            : (filterDirection as PptxAnimationEffect['direction']) ||
              DIRECTIONS[node.attr('presetSubtype') || ''] ||
              'bottom';
      timeline.steps[timeline.steps.length - 1].effects.push({
        elementIds: [
          ...new Set(targets.map((target) => target.attr('spid') || '').filter(Boolean)),
        ],
        effect,
        phase: presetClass === 'exit' ? 'out' : 'in',
        direction,
        ...(paragraphRange ? { paragraphRange } : {}),
        ...(targets[0].child('bg').exists() ? { backgroundOnly: true } : {}),
        delayMs: start,
        durationMs,
      });
      lastStart = start;
      lastEnd = start + durationMs;
      return;
    }
    for (const child of node.allChildren()) visit(child, [...parents, node]);
  }
  visit(timing, []);
  timeline.steps = timeline.steps
    .map((step) => ({
      ...step,
      effects: step.effects.filter(
        (effect) => !effect.elementIds.some((id) => unsupportedTargets.has(id)),
      ),
    }))
    .filter((step) => step.effects.length);
  return timeline;
}
