import type { Action, PPTElement } from '@openmaic/dsl';

export const SPEECH_FOCUS_CONTRACT = `【讲解与聚焦生成合同】
把每个可指认知识点生成为同时包含 targetId 和 speech 的教学片段；由代码转换为聚焦和讲解动作，不要输出零散动作数组。
每段主体讲稿都要声明自己的目标；同一目标分成多段时，每段重复该 targetId。比较表格的实际行列属于主体讲解，不属于无聚焦的整页概览。
一个片段只能解释同一个可见区域；讲到另一个区域、步骤或报错类型之前，必须结束当前片段，切换目标后再生成新的片段。禁止把“第二个，某概念”放在前一个目标的讲稿末尾。
只选择本页真实存在的教学元素；比较表格时指向表格，不要指向页标题、建议框或装饰。下方完整元素内容优先于截断的摘要。
过渡、开场和整页概览可以不聚焦。没有足够证据确定目标时不要猜测。不能为了通过检查而删掉必要教学内容或把主体讲解全部改成不聚焦。
结论在推导后首次讲解时可设置 revealBefore=true，由代码先揭示再聚焦和讲解；保留结论在推导后揭示的教学安排。
保持课程的内容深度、时长预算、语言要求；增加或压缩讲解都必须保持上述单元边界。`;

export interface SpeechFocusSegment {
  speechId: string;
  text: string;
  targetIds: string[];
}

export function teachingInventory(elements: PPTElement[]) {
  return elements.map((element) => {
    const record = element as unknown as Record<string, unknown>;
    const text =
      element.type === 'table'
        ? element.data.map((row) => row.map((cell) => cell.text).join(' | ')).join('\n')
        : [record.content, record.text, record.latex, record.alt, record.name, record.description]
            .filter((value): value is string => typeof value === 'string')
            .join(' ');
    const shapeText = element.type === 'shape' ? element.text?.content : undefined;
    return {
      id: element.id,
      type: element.type,
      ...(element.type === 'video' ? { hasMediaSource: !!element.src } : {}),
      text: shapeText ? `${text} ${shapeText}` : text,
      ...(element.type === 'chart'
        ? { chartType: element.chartType, chartData: element.data }
        : {}),
      left: element.left,
      top: element.top,
      width: element.width,
      height: record.height,
    };
  });
}

/** Pure structural checks; semantic approval is a separate model call. */
export function inspectSpeechFocus(actions: Action[], elements: PPTElement[]) {
  const known = new Set(elements.map((element) => element.id));
  const hidden = new Set(
    actions.filter((action) => action.type === 'reveal').map((action) => action.elementId),
  );
  const issues: string[] = [];
  const segments: SpeechFocusSegment[] = [];
  const speechIds = new Set<string>();
  const actionIds = new Set<string>();
  let pending = new Set<string>();
  for (const action of actions) {
    if (!action.id || actionIds.has(action.id))
      issues.push('Action ids must be present and unique');
    actionIds.add(action.id);
    if (action.type === 'reveal') {
      if (!known.has(action.elementId)) issues.push(`reveal ${action.id}: target does not exist`);
      hidden.delete(action.elementId);
    } else if (action.type === 'spotlight' || action.type === 'laser') {
      if (!known.has(action.elementId)) issues.push(`cue ${action.id}: target does not exist`);
      if (hidden.has(action.elementId))
        issues.push(`cue ${action.id}: target must be revealed first`);
      pending.add(action.elementId);
    } else if (action.type === 'speech') {
      if (!action.id || speechIds.has(action.id))
        issues.push('Speech ids must be present and unique');
      speechIds.add(action.id);
      if (!action.text?.trim()) issues.push(`speech ${action.id}: empty narration`);
      if (pending.size > 1) issues.push(`speech ${action.id}: multiple different focus targets`);
      segments.push({ speechId: action.id, text: action.text, targetIds: [...pending] });
      pending = new Set();
    } else if (action.type !== 'discussion') {
      if (pending.size) issues.push(`cue before ${action.id} is not paired with speech`);
      pending = new Set();
    }
  }
  if (pending.size) issues.push('Trailing focus cue has no speech');
  if (!segments.length) issues.push('No narration was generated');
  return { issues, segments };
}

/** Every final speech must receive an explicit verdict for its exact target. */
export function parseFocusReview(response: string, expected: SpeechFocusSegment[]): string[] {
  let report: unknown;
  try {
    report = JSON.parse(
      response
        .trim()
        .replace(/^```(?:json)?\s*/i, '')
        .replace(/\s*```$/, ''),
    );
  } catch {
    return ['Semantic reviewer returned invalid JSON'];
  }
  if (
    !report ||
    typeof report !== 'object' ||
    !('segments' in report) ||
    !Array.isArray(report.segments)
  )
    return ['Semantic reviewer omitted per-speech verdicts'];
  const verdicts = report.segments as Array<Record<string, unknown>>;
  if (verdicts.length !== expected.length)
    return ['Semantic reviewer did not cover every speech exactly once'];
  const issues: string[] = [];
  for (const segment of expected) {
    const matches = verdicts.filter((verdict) => verdict && verdict.speechId === segment.speechId);
    const verdict = matches[0];
    if (
      matches.length !== 1 ||
      !Array.isArray(verdict.targetIds) ||
      JSON.stringify(verdict.targetIds) !== JSON.stringify(segment.targetIds)
    ) {
      issues.push(`speech ${segment.speechId}: reviewer omitted or changed the binding`);
    } else if (verdict.matches !== true || verdict.singleTopic !== true) {
      issues.push(
        `speech ${segment.speechId}: ${typeof verdict.reason === 'string' ? verdict.reason.slice(0, 400) : 'Target and narration do not match, or narration crosses visual topics'}`,
      );
    }
  }
  return issues;
}
