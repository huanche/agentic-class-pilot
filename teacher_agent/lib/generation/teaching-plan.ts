import type { Action, PPTElement } from '@openmaic/dsl';
import { inspectSpeechFocus } from './speech-focus-contract';

export const TEACHING_PLAN_SYSTEM = `[SLIDE_TEACHING_PLAN]
You write a teacher's narration as atomic teaching segments, each binding ONE real slide region to its EXACT spoken text. The application compiles these segments into playback actions. Do not output loose actions.
Return only JSON: {"segments":[
  {"kind":"narration","purpose":"opening","targetId":null,"speech":"Neutral opening."},
  {"kind":"narration","purpose":"explanation","targetId":"REAL_ELEMENT_ID","speech":"Explain only this region.","focus":"spotlight","revealBefore":false}
]}.
Narration fields: kind, purpose (explanation/opening/transition/overview), targetId (one exact element ID or null), speech, optional focus (spotlight/laser), optional revealBefore (boolean). No IDs, audio, duration, timestamps, or additional fields.
Every substantive explanation MUST use purpose=explanation with a real targetId. Do not disguise teaching as an unfocused introduction or overview. Explaining or comparing a table's rows targets the TABLE, not its title or advice box. Read full element evidence including all table cells, chart data and shape text.
Each paragraph must stay on its one target from beginning to end. Split BEFORE introducing another region, step or error type. Multiple paragraphs about the same target repeat its targetId. Preserve natural explanations and the requested teaching depth and narration budget; do not shorten the lesson to evade checks.
Only neutral openings, transitions and whole-page overviews may use targetId=null. Never guess missing image details. A title is not a substitute for a specific example being explained.
Use revealBefore=true only on the FIRST explanation of a distinct conclusion/answer that should stay hidden until earlier supporting explanations finish. Do not use its target earlier or reveal it twice. The compiler will reveal, focus and speak in that order.
Keep same-session continuity: greet only on the first page, continue naturally on middle pages, summarize on the last. Use the provided language directive. Teacher monologue only: no simulated student dialogue, speaker labels, stage directions, generation instructions or timing budgets read aloud.
To play an actual video, use {"kind":"video","targetId":"REAL_VIDEO_ID"}, preceded by a short spoken introduction. Do not explain a video while it is playing.
Optional discussion: {"kind":"discussion","topic":"...","prompt":"...","agentId":"REAL_STUDENT_ID"}. prompt and agentId are optional. Discussion must be the LAST segment; normally omit it, at most 1-2 discussions per course. Never impersonate that student in the narration.
The user message contains teaching context and read-only element data. Return the complete plan, including when correcting previous issues. Never output a partial patch.`;

const object = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === 'string' && !!value.trim();

/** Strict boundary: invalid plans produce no actions and never choose fallback targets. */
export function compileTeachingPlan(
  response: string,
  elements: PPTElement[],
  studentIds: string[],
  idPrefix: string,
): { actions: Action[]; issues: string[] } {
  let plan: unknown;
  try {
    plan = JSON.parse(
      response
        .trim()
        .replace(/^```(?:json)?\s*/i, '')
        .replace(/\s*```$/, ''),
    );
  } catch {
    return { actions: [], issues: ['Teaching plan must be complete valid JSON'] };
  }
  if (!object(plan) || !Array.isArray(plan.segments) || !plan.segments.length)
    return { actions: [], issues: ['Teaching plan must contain a non-empty segments array'] };
  const issues: string[] = [];
  const actions: Action[] = [];
  const known = new Map(elements.map((element) => [element.id, element]));
  if (known.size !== elements.length || elements.some((element) => !text(element.id)))
    return { actions: [], issues: ['Slide element IDs must be present and unique'] };
  const revealed = new Set<string>();
  for (const [index, segment] of plan.segments.entries()) {
    const at = `segment ${index + 1}`;
    const id = `${idPrefix}-${index + 1}`;
    if (!object(segment)) {
      issues.push(`${at}: must be an object`);
      continue;
    }
    const keys =
      segment.kind === 'narration'
        ? ['kind', 'purpose', 'targetId', 'speech', 'focus', 'revealBefore']
        : segment.kind === 'video'
          ? ['kind', 'targetId']
          : segment.kind === 'discussion'
            ? ['kind', 'topic', 'prompt', 'agentId']
            : [];
    if (Object.keys(segment).some((key) => !keys.includes(key)))
      issues.push(`${at}: unsupported fields; use the teaching segment schema`);
    if (segment.kind === 'narration') {
      const { targetId, purpose, speech, focus, revealBefore } = segment;
      if (
        typeof purpose !== 'string' ||
        !['explanation', 'opening', 'transition', 'overview'].includes(purpose)
      )
        issues.push(`${at}: invalid narration purpose`);
      if (!text(speech)) issues.push(`${at}: narration must be non-empty text`);
      if (targetId !== null && (!text(targetId) || !known.has(targetId)))
        issues.push(`${at}: targetId must be null or an existing element ID`);
      if (purpose === 'explanation' && !text(targetId))
        issues.push(`${at}: explanation requires its own targetId`);
      if (focus !== undefined && focus !== 'spotlight' && focus !== 'laser')
        issues.push(`${at}: invalid focus`);
      if (revealBefore !== undefined && typeof revealBefore !== 'boolean')
        issues.push(`${at}: revealBefore must be boolean`);
      if (targetId === null && (revealBefore === true || focus !== undefined))
        issues.push(`${at}: an unfocused transition cannot reveal or focus a target`);
      if (text(targetId)) {
        if (revealBefore === true) {
          if (revealed.has(targetId)) issues.push(`${at}: target may only be revealed once`);
          revealed.add(targetId);
          actions.push({
            id: `${id}-reveal`,
            type: 'reveal',
            elementId: targetId,
            effect: 'fade-up',
            duration: 520,
          });
        }
        actions.push({
          id: `${id}-focus`,
          type: focus === 'laser' ? 'laser' : 'spotlight',
          elementId: targetId,
        });
      }
      if (text(speech))
        actions.push({ id: `${id}-speech`, type: 'speech', text: speech, audioInvalidated: true });
    } else if (segment.kind === 'video') {
      const video = text(segment.targetId) ? known.get(segment.targetId) : undefined;
      if (video?.type !== 'video' || !video.src)
        issues.push(`${at}: video requires an existing video with a media source`);
      else actions.push({ id: `${id}-video`, type: 'play_video', elementId: video.id });
    } else if (segment.kind === 'discussion') {
      if (!text(segment.topic) || index !== plan.segments.length - 1)
        issues.push(`${at}: discussion needs a topic and must be last`);
      if (segment.prompt !== undefined && !text(segment.prompt))
        issues.push(`${at}: invalid discussion prompt`);
      if (
        segment.agentId !== undefined &&
        (!text(segment.agentId) || !studentIds.includes(segment.agentId))
      )
        issues.push(`${at}: discussion agent must be a provided student`);
      if (text(segment.topic))
        actions.push({
          id: `${id}-discussion`,
          type: 'discussion',
          topic: segment.topic,
          ...(text(segment.prompt) ? { prompt: segment.prompt } : {}),
          ...(text(segment.agentId) ? { agentId: segment.agentId } : {}),
        });
    } else issues.push(`${at}: unsupported segment kind`);
  }
  if (!issues.length) issues.push(...inspectSpeechFocus(actions, elements).issues);
  return { actions: issues.length ? [] : actions, issues };
}
