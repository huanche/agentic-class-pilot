import type { SceneOutline, UserRequirements } from '@/lib/types/generation';
import type { Scene } from '@/lib/types/stage';
import { WIDGET_MS } from '@/lib/choreography/timing';

export const DEFAULT_TARGET_MINUTES = 28;
export const DURATION_TOLERANCE = 0.05;
export const MAX_DURATION_CORRECTIONS = 2;
export type DurationStatus = 'unmeasured' | 'within-tolerance' | 'too-short' | 'too-long';
export interface DurationFeedback {
  measuredSeconds: number;
  targetSeconds: number;
}

/** Blank is an intentional default; malformed explicit values must never silently become 28. */
export function resolveCourseMinutes(value: unknown): number {
  if (value == null || (typeof value === 'string' && !value.trim())) return DEFAULT_TARGET_MINUTES;
  if (typeof value !== 'number' && typeof value !== 'string') {
    throw new Error('课件时长请输入正整数分钟；留空默认 28 分钟。');
  }
  const minutes = Number(value);
  if (!Number.isSafeInteger(minutes) || minutes <= 0 || !Number.isSafeInteger(minutes * 60)) {
    throw new Error('课件时长请输入正整数分钟；留空默认 28 分钟。');
  }
  return minutes;
}

export function withCourseDurationRequirement(requirements: UserRequirements): UserRequirements {
  const minutes = resolveCourseMinutes(requirements.targetDurationMinutes);
  return {
    ...requirements,
    targetDurationMinutes: minutes,
    requirement: `${requirements.requirement}\n\n【课程内容与播放时长合同】\n教师设置的自动讲解与演示目标为 ${minutes} 分钟（${minutes * 60} 秒），以此结构化设置为准。时长应来自有价值的教学内容增加，而不是修改计时字段。请据此规划知识点深度、页数与各页 estimatedDuration（秒）：需要更长讲解时，围绕教学目标增加有依据的具体案例、逐步推导、对比辨析、演示过程或迁移应用，并在大纲中写明相应教学环节；AI 增强模式可增加必要的例题页或演示页。目标不包含教师暂停、学生自主答题、PBL/自由讨论和网络等待。不得用重复内容、静音、空白等待或超慢语速凑时长，也不得偏离课程范围或编造事实。高保真模式保留原始画布和页数，通过原稿知识点的讲解深度、例子和推演丰富内容。材料不足时应保持诚实，实际是否达标以生成音频实测为准。`,
  };
}

/** Give the visual-content model teaching depth, before narration/actions are generated. */
export function withSceneContentDuration(outline: SceneOutline): SceneOutline {
  const seconds = outline.durationBudget?.targetSeconds;
  if (!(seconds && Number.isFinite(seconds) && seconds > 0)) return outline;
  return {
    ...outline,
    description: `${outline.description}\n\n【本页内容深度要求】\n按正常授课节奏，本页需要支撑约 ${seconds} 秒的有效讲解与演示。请围绕原有教学目标，把必要的原理解释、具体案例、计算/推导步骤、对比辨析或演示状态设计为可见且可指认的页面内容；根据学科和材料选择适合的环节，不要机械堆齐所有类型。较长的讲解应有更多有价值的内容支撑，不能仅增加空泛的旁白。将关键步骤、例子或结论设计成清晰的层次，必要时可逐步 reveal；保持字号、留白与可读性，不能为了时长把文字挤满一页。不得将时间预算或内部指令写到课件画面上，不得超出材料支持范围编造知识。`,
  };
}

/** Largest-remainder allocation: exact integer sum, with model estimates used only as weights. */
export function planCourseDuration(outlines: SceneOutline[], minutes: number): SceneOutline[] {
  const total = resolveCourseMinutes(minutes) * 60;
  const automatic = outlines.filter((page) => page.type === 'slide' || page.type === 'interactive');
  if (!automatic.length) return outlines.map((page) => ({ ...page, durationBudget: undefined }));
  if (automatic.length > total) throw new Error('页面数量超过目标秒数，请增加时长或减少页面。');
  const weights = automatic.map((page) =>
    Number.isFinite(page.estimatedDuration) && page.estimatedDuration! > 0
      ? page.estimatedDuration!
      : 60,
  );
  const weightSum = weights.reduce((sum, weight) => sum + weight, 0);
  const raw = weights.map((weight) => (weight / weightSum) * total);
  const allocated = raw.map((value) => Math.max(1, Math.floor(value)));
  let difference = total - allocated.reduce((sum, value) => sum + value, 0);
  const descending = raw
    .map((value, i) => ({ i, remainder: value - Math.floor(value) }))
    .sort((a, b) => b.remainder - a.remainder || a.i - b.i);
  while (difference > 0) {
    for (const { i } of descending) {
      if (!difference) break;
      allocated[i]++;
      difference--;
    }
  }
  while (difference < 0) {
    for (const { i } of [...descending].reverse()) {
      if (!difference) break;
      if (allocated[i] > 1) {
        allocated[i]--;
        difference++;
      }
    }
  }
  let index = 0;
  return outlines.map((page) => {
    if (page.type !== 'slide' && page.type !== 'interactive')
      return { ...page, durationBudget: undefined };
    const targetSeconds = allocated[index++];
    return { ...page, estimatedDuration: targetSeconds, durationBudget: { targetSeconds } };
  });
}

export function withNarrationDuration(
  outline: SceneOutline,
  feedback?: DurationFeedback,
): SceneOutline {
  const seconds = outline.durationBudget?.targetSeconds;
  if (!(seconds && Number.isFinite(seconds) && seconds > 0)) return outline;
  // A first-pass speaking rate is only a prompt estimate. Real TTS below decides success.
  const characters = Math.round(seconds * 3.5);
  const words = Math.round((seconds / 60) * 135);
  return {
    ...outline,
    description: `${outline.description}\n\n【本页播放时长合同（优先于通用讲稿字数建议）】\n本页自动讲解与演示预算 ${seconds} 秒，容差 ±5%。首轮可按中文约 ${characters} 字或英文约 ${words} 词组织自然口语，按实际授课语言选择；这只是估算，不能把估算当作音频实测。不要沿用固定的 140–200 字限制。内容应解释原理、提供适量例子与推演，所有例子必须以本页知识点为依据；不要重复堆砌。为 reveal 等同步动作留少量时间，聚焦和激光笔不额外占讲解时间。保留必要的 reveal 结论揭示。禁止用长时间静音、无意义等待、重复内容、极端慢速或截断语音来凑时长。${feedback ? `\n【实测校正】上一版实际自动播放 ${feedback.measuredSeconds.toFixed(1)} 秒，目标 ${feedback.targetSeconds} 秒。请按目标与实测之比调整讲解的深度和长度，保留核心知识点及必要动作；不要增加没有材料依据的事实。` : ''}`,
  };
}

export function durationStatus(actual: number | undefined, target: number): DurationStatus {
  if (actual == null || !Number.isFinite(actual) || actual <= 0 || target <= 0) return 'unmeasured';
  const error = (actual - target) / target;
  if (Math.abs(error) <= DURATION_TOLERANCE + Number.EPSILON) return 'within-tolerance';
  return error < 0 ? 'too-short' : 'too-long';
}

/** Only complete, supported timelines are called measured. Unknown video/board time stays unknown. */
export function measureScenePlaybackSeconds(
  scene: Scene,
  audioSecondsByAction: Record<string, number | undefined>,
): number | undefined {
  let seconds = 0;
  for (const action of scene.actions ?? []) {
    switch (action.type) {
      case 'speech': {
        const duration = audioSecondsByAction[action.id];
        if (duration == null || !Number.isFinite(duration) || duration <= 0) return undefined;
        seconds += duration;
        break;
      }
      case 'reveal':
        seconds += Math.max(120, Math.min(action.duration ?? 520, 2000)) / 1000;
        break;
      case 'widget_highlight':
      case 'widget_setState':
      case 'widget_annotation':
      case 'widget_reveal':
        seconds += WIDGET_MS / 1000;
        break;
      case 'spotlight':
      case 'laser':
      case 'discussion':
        break;
      default:
        return undefined;
    }
  }
  return seconds > 0 ? seconds : undefined;
}

export function durationMeasurementKey(scene: Scene): string {
  // Reference conversion changes ids/URLs without changing the rendered audio.
  const text = JSON.stringify((scene.actions ?? []).map((action) => {
    if (action.type !== 'speech') return action;
    const transport = action as typeof action & { audioUrl?: string; audioRef?: string };
    return { id: action.id, type: action.type, text: action.text, speed: action.speed ?? 1,
      hasAudio: Boolean(action.audioId || transport.audioUrl || transport.audioRef),
      invalidated: Boolean(action.audioInvalidated) };
  }));
  let hash = 2166136261;
  for (let index = 0; index < text.length; index++)
    hash = Math.imul(hash ^ text.charCodeAt(index), 16777619);
  return `${text.length}:${hash >>> 0}`;
}

/** Editing narration/actions invalidates the earlier measurement without rewriting editor state. */
export function measuredSceneSeconds(scene: Scene): number | undefined {
  if (scene.timing?.measurementKey && scene.timing.measurementKey !== durationMeasurementKey(scene))
    return undefined;
  const value = scene.timing?.measuredDurationSec;
  return value != null && Number.isFinite(value) && value > 0 ? value : undefined;
}

export function assessCourseDuration(
  scenes: Scene[],
  minutes: number,
  expectedAutomaticPages: number,
) {
  const pages = scenes.filter((page) => page.type === 'slide' || page.type === 'interactive');
  const complete =
    pages.length > 0 &&
    pages.length === expectedAutomaticPages &&
    pages.every((page) => measuredSceneSeconds(page) != null);
  const actualSeconds = complete
    ? pages.reduce((sum, page) => sum + measuredSceneSeconds(page)!, 0)
    : undefined;
  const targetSeconds = resolveCourseMinutes(minutes) * 60;
  return {
    targetSeconds,
    actualSeconds,
    status: durationStatus(actualSeconds, targetSeconds),
    measuredPages: pages.filter((page) => measuredSceneSeconds(page) != null).length,
    expectedPages: expectedAutomaticPages,
  };
}

/** Never pads or cuts audio. At most two paid corrections; keep the closest usable candidate. */
export async function calibrateNarrationDuration(
  initial: Scene,
  callbacks: {
    regenerate: (feedback: DurationFeedback, previous: Scene) => Promise<Scene>;
    dispose: (scene: Scene) => Promise<void>;
  },
): Promise<Scene> {
  const target = initial.timing?.plannedDurationSec ?? 0;
  let best = initial;
  let attempts = 0;
  const error = (page: Scene) =>
    page.timing?.measuredDurationSec == null
      ? Infinity
      : Math.abs(page.timing.measuredDurationSec - target);
  while (
    attempts < MAX_DURATION_CORRECTIONS &&
    ['too-short', 'too-long'].includes(durationStatus(best.timing?.measuredDurationSec, target))
  ) {
    attempts++;
    let candidate: Scene;
    try {
      candidate = await callbacks.regenerate(
        { measuredSeconds: best.timing!.measuredDurationSec!, targetSeconds: target },
        best,
      );
    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') {
        await callbacks.dispose(best);
        throw err;
      }
      break; // Preserve a playable draft on provider/model failure.
    }
    if (error(candidate) < error(best)) {
      await callbacks.dispose(best);
      best = candidate;
    } else {
      await callbacks.dispose(candidate);
    }
  }
  best.timing = {
    ...best.timing,
    correctionAttempts: attempts,
    durationStatus: durationStatus(best.timing?.measuredDurationSec, target),
  };
  return best;
}
