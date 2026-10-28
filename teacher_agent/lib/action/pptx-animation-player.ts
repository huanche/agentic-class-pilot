import type { PptxAnimationEffect, PptxAnimationStep } from '@openmaic/dsl';
import { useCanvasStore } from '@/lib/store/canvas';
import {
  pptxBackgroundKey,
  pptxEffectTargetKeys,
  pptxStepDurationMs,
} from '@/lib/import/pptx-animations';

type TargetNode = HTMLElement | SVGElement;
interface EffectTarget {
  key: string;
  effect: PptxAnimationEffect;
  node?: TargetNode;
}

function effectTargets(effect: PptxAnimationEffect): EffectTarget[] {
  return effect.elementIds.flatMap<EffectTarget>((id) => {
    const root =
      typeof document === 'undefined'
        ? undefined
        : (document.getElementById(`screen-element-${id}`) ?? undefined);
    if (effect.backgroundOnly)
      return [
        {
          key: pptxBackgroundKey(id),
          effect: { ...effect, elementIds: [id] },
          node:
            root?.querySelector<SVGElement>(
              '.base-element-shape > .rotate-wrapper > .element-content > svg',
            ) ?? undefined,
        },
      ];
    if (!effect.paragraphRange)
      return [{ key: id, effect: { ...effect, elementIds: [id] }, node: root }];
    return Array.from(
      { length: effect.paragraphRange.end - effect.paragraphRange.start + 1 },
      (_, i) => {
        const paragraph = effect.paragraphRange!.start + i;
        const single = {
          ...effect,
          elementIds: [id],
          paragraphRange: { start: paragraph, end: paragraph },
        };
        return {
          key: pptxEffectTargetKeys(single)[0],
          effect: single,
          node:
            root?.querySelector<HTMLElement>(`[data-pptx-paragraph="${paragraph}"]`) ?? undefined,
        };
      },
    );
  });
}

/** Full-canvas wrappers keep the original child geometry; clipping uses that child's bounds. */
export function pptxAnimationFrames(effect: PptxAnimationEffect, node?: Element): Keyframe[] {
  let frames: Keyframe[];
  const direction = effect.direction ?? 'bottom';
  if (effect.effect === 'fly') {
    const offset = { left: '-110%, 0', right: '110%, 0', top: '0, -110%', bottom: '0, 110%' }[
      direction
    ];
    frames = [
      { transform: `translate(${offset})`, opacity: 1 },
      { transform: 'translate(0, 0)', opacity: 1 },
    ];
  } else if (effect.effect === 'zoom') {
    frames = [
      { transform: 'scale(0)', opacity: 0 },
      { transform: 'scale(1)', opacity: 1 },
    ];
  } else if (effect.effect === 'wipe' || effect.effect === 'box') {
    const content =
      effect.paragraphRange || effect.backgroundOnly
        ? node
        : (node?.querySelector('.slide-element-hit-target')?.firstElementChild ??
          node?.firstElementChild);
    const box = content?.getBoundingClientRect();
    const root = node?.getBoundingClientRect();
    const x = root?.width && box ? ((box.left - root.left) / root.width) * 100 : 0;
    const y = root?.height && box ? ((box.top - root.top) / root.height) * 100 : 0;
    const w = root?.width && box ? (box.width / root.width) * 100 : 100;
    const h = root?.height && box ? (box.height / root.height) * 100 : 100;
    const clip =
      effect.effect === 'box'
        ? `inset(${y + h / 2}% ${100 - x - w / 2}% ${100 - y - h / 2}% ${x + w / 2}%)`
        : direction === 'left'
          ? `inset(${y}% ${100 - x}% ${100 - y - h}% ${x}%)`
          : direction === 'right'
            ? `inset(${y}% ${100 - x - w}% ${100 - y - h}% ${x + w}%)`
            : direction === 'top'
              ? `inset(${y}% ${100 - x - w}% ${100 - y}% ${x}%)`
              : `inset(${y + h}% ${100 - x - w}% ${100 - y - h}% ${x}%)`;
    frames = [{ clipPath: clip }, { clipPath: 'inset(0%)' }];
  } else {
    frames = [{ opacity: effect.effect === 'appear' ? 1 : 0 }, { opacity: 1 }];
  }
  return effect.phase === 'out' ? [...frames].reverse() : frames;
}

/** One controllable clock drives all concurrent effects, including pause, speed and cancellation. */
export class PptxAnimationPlayer {
  private frame: ReturnType<typeof setTimeout> | undefined;
  private elapsed = 0;
  private lastTime = 0;
  private rate = 1;
  private paused = false;
  private running: Array<{
    key: string;
    effect: PptxAnimationEffect;
    node?: TargetNode;
    animation?: Animation;
    started: boolean;
    finished: boolean;
  }> = [];
  private completion?: { promise: Promise<void>; resolve: () => void; duration: number };

  get active() {
    return !!this.completion;
  }
  get elapsedMs(): number {
    this.advance();
    return this.elapsed;
  }
  setRate(rate: number) {
    if (Number.isFinite(rate) && rate > 0) {
      this.advance();
      this.rate = rate;
    }
  }

  play(step: PptxAnimationStep, silent = false): Promise<void> {
    this.cancel();
    if (silent) {
      for (const effect of [...step.effects].sort(
        (a, b) => a.delayMs + a.durationMs - b.delayMs - b.durationMs,
      ))
        this.finishEffect(effect);
      return Promise.resolve();
    }
    this.elapsed = 0;
    this.paused = false;
    this.lastTime = Date.now();
    this.running = step.effects.flatMap((effect) =>
      effectTargets(effect).map((target) => ({
        ...target,
        started: false,
        finished: false,
      })),
    );
    let resolve!: () => void;
    const promise = new Promise<void>((done) => {
      resolve = done;
    });
    this.completion = { promise, resolve, duration: pptxStepDurationMs(step) };
    this.tick();
    return promise;
  }

  private finishEffect(effect: PptxAnimationEffect, node?: TargetNode) {
    const store = useCanvasStore.getState();
    const ids = new Set(pptxEffectTargetKeys(effect));
    const hidden = store.hiddenElementIdList.filter((id) => !ids.has(id));
    if (effect.phase === 'out') hidden.push(...ids);
    store.setHiddenElementIdList([...new Set(hidden)]);
    for (const match of effectTargets(effect)) {
      const target = node ?? match.node;
      if (target) target.style.visibility = effect.phase === 'out' ? 'hidden' : 'visible';
    }
  }

  private advance() {
    if (!this.completion || this.paused) return;
    const now = Date.now();
    this.elapsed += Math.max(0, now - this.lastTime) * this.rate;
    this.lastTime = now;
  }

  private tick = () => {
    if (!this.completion || this.paused) return;
    this.advance();
    const ordered = [...this.running].sort((a, b) => a.effect.delayMs - b.effect.delayMs);
    for (const item of ordered) {
      if (item.finished) continue;
      if (this.elapsed < item.effect.delayMs) continue;
      if (!item.started) {
        // Scene changes commit their new canvas asynchronously. Resolve again after the
        // first frame instead of permanently capturing the outgoing page's DOM.
        item.node ??= effectTargets(item.effect).find((target) => target.key === item.key)?.node;
        if (!item.node && typeof document !== 'undefined') continue;
        item.started = true;
        if (item.effect.phase === 'in') {
          const store = useCanvasStore.getState();
          store.setHiddenElementIdList(store.hiddenElementIdList.filter((id) => id !== item.key));
        }
        if (item.node) {
          item.node.style.visibility = 'visible';
          item.node.style.animation = 'none';
          if (item.effect.effect === 'zoom') {
            const content =
              item.node.querySelector('.slide-element-hit-target')?.firstElementChild ??
              item.node.firstElementChild;
            const box = content?.getBoundingClientRect();
            const root = item.node.getBoundingClientRect();
            if (box && root.width && root.height)
              item.node.style.transformOrigin = `${((box.left + box.width / 2 - root.left) / root.width) * 100}% ${((box.top + box.height / 2 - root.top) / root.height) * 100}%`;
          }
          if (item.node.animate) {
            item.animation = item.node.animate(pptxAnimationFrames(item.effect, item.node), {
              duration: Math.max(1, item.effect.durationMs),
              fill: 'both',
              easing: 'linear',
            });
            item.animation.pause();
          }
        }
      }
      if (item.animation) item.animation.currentTime = this.elapsed - item.effect.delayMs;
      if (this.elapsed >= item.effect.delayMs + item.effect.durationMs) {
        item.finished = true;
        this.finishEffect(item.effect, item.node);
        item.animation?.cancel();
      }
    }
    if (this.elapsed >= this.completion.duration) {
      for (const item of this.running)
        if (!item.finished) this.finishEffect(item.effect, item.node);
      const done = this.completion;
      this.completion = undefined;
      this.running = [];
      done.resolve();
    } else
      this.frame = setTimeout(
        this.tick,
        Math.min(16, (this.completion.duration - this.elapsed) / this.rate),
      );
  };

  pause() {
    this.advance();
    this.paused = true;
    clearTimeout(this.frame);
  }
  resume(): Promise<void> | undefined {
    if (!this.completion) return undefined;
    this.paused = false;
    this.lastTime = Date.now();
    this.tick();
    return this.completion?.promise ?? Promise.resolve();
  }
  cancel() {
    clearTimeout(this.frame);
    this.running.forEach((item) => item.animation?.cancel());
    this.running = [];
    const done = this.completion;
    this.completion = undefined;
    done?.resolve();
  }
}
