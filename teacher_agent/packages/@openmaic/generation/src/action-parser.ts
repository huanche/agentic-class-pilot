/**
 * Action Parser - converts structured JSON Array output to Action[]
 *
 * Bridges the stateless-generate parser (used for online streaming) with the
 * offline generation pipeline, producing typed Action objects that preserve
 * the original interleaving order from the LLM output.
 *
 * For complete (non-streaming) responses, uses JSON.parse with partial-json
 * fallback for robustness.
 */

import type { Action, ActionType } from '@openmaic/dsl';
import { isActionType, SLIDE_ONLY_ACTIONS } from '@openmaic/dsl';
import { nanoid } from 'nanoid';
import { parse as parsePartialJson, Allow } from 'partial-json';
import { jsonrepair } from 'jsonrepair';
import { noopGenerationLogger, type GenerationLogger } from './logger.js';

/** A bad model document, not a provider/network failure. Recovery is bounded by the caller. */
export class ActionOutputFormatError extends Error {
  readonly isRetryable = false;

  constructor(message: string) {
    super(message);
    this.name = 'ActionOutputFormatError';
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function actionId(item: Record<string, unknown>): string {
  const id = item.action_id ?? item.tool_id ?? item.id;
  return typeof id === 'string' && id.trim() ? id : `action_${nanoid(8)}`;
}

function speechAction(item: Record<string, unknown>, id: string): Action | undefined {
  const text = item.text ?? item.content;
  if (typeof text !== 'string') {
    throw new ActionOutputFormatError('speech requires string text or content');
  }
  if (!text.trim()) return undefined;
  return { ...item, id, type: 'speech', text: text.trim() } as Action;
}

/**
 * Strip markdown code fences (```json ... ``` or ``` ... ```) from a response string.
 */
function stripCodeFences(text: string): string {
  // Remove opening ```json or ``` and closing ```
  return text.replace(/^```(?:json)?\s*\n?/i, '').replace(/\n?\s*```\s*$/i, '');
}

/**
 * Parse a complete LLM response in JSON Array format into an ordered Action[] array.
 *
 * Expected format (new):
 * [{"type":"action","name":"spotlight","params":{"elementId":"..."}},
 *  {"type":"text","content":"speech content"},...]
 *
 * Also supports legacy format:
 * [{"type":"action","tool_name":"spotlight","parameters":{"elementId":"..."}},...]
 *
 * Text items become `speech` actions; action items are converted to their
 * respective action types (spotlight, discussion, etc.).
 * The original interleaving order is preserved.
 */
export function parseActionsFromStructuredOutput(
  response: string,
  sceneType?: string,
  allowedActions?: string[],
  logger: GenerationLogger = noopGenerationLogger,
): Action[] {
  const log = logger;
  // Step 1: Strip markdown code fences if present
  const cleaned = stripCodeFences(response.trim());

  // Step 2: Find the JSON array range
  const startIdx = cleaned.indexOf('[');
  const endIdx = cleaned.lastIndexOf(']');

  if (startIdx === -1) {
    log.warn('No JSON array found in response');
    throw new ActionOutputFormatError('No JSON action array found in response');
  }

  const jsonStr = endIdx > startIdx ? cleaned.slice(startIdx, endIdx + 1) : cleaned.slice(startIdx); // unclosed array — let partial-json handle it

  // Step 3: Parse — try JSON.parse first, then jsonrepair, fallback to partial-json
  let items: unknown[];
  try {
    items = JSON.parse(jsonStr);
  } catch {
    // Try jsonrepair to fix malformed JSON (e.g. unescaped quotes in Chinese text)
    try {
      items = JSON.parse(jsonrepair(jsonStr));
      log.info('Recovered malformed JSON via jsonrepair');
    } catch {
      try {
        items = parsePartialJson(
          jsonStr,
          Allow.ARR | Allow.OBJ | Allow.STR | Allow.NUM | Allow.BOOL | Allow.NULL,
        );
      } catch (e) {
        log.warn('Failed to parse JSON array:', (e as Error).message);
        throw new ActionOutputFormatError('Cannot parse JSON action array');
      }
    }
  }

  if (!Array.isArray(items)) {
    log.warn('Parsed result is not an array');
    throw new ActionOutputFormatError('Action output must be a JSON array');
  }

  // Step 4: Convert items to Action[]
  const actions: Action[] = [];

  for (const item of items) {
    if (!isRecord(item)) {
      throw new ActionOutputFormatError('Each action item must be an object');
    }
    const id = actionId(item);
    let action: Action | undefined;
    if (item.type === 'text' || item.type === 'speech') {
      action = speechAction(item, id);
    } else if (item.type === 'action') {
      // Support the envelope and legacy tool formats, but never let params
      // overwrite the envelope's type/id. "text" is narration, not a DSL verb.
      const name = item.name ?? item.tool_name;
      const params = item.params ?? item.parameters ?? {};
      if (!isRecord(params)) {
        throw new ActionOutputFormatError('Action params must be an object');
      }
      action =
        name === 'text' || name === 'speech'
          ? speechAction(params, id)
          : ({ ...params, id, type: name as Action['type'] } as Action);
    } else if (isActionType(item.type)) {
      action = { ...item, id } as Action;
    } else {
      throw new ActionOutputFormatError(`unknown action type: ${JSON.stringify(item.type)}`);
    }
    // Keep the existing widget default without weakening the DSL validator.
    if (action?.type === 'widget_setState' && action.state == null) {
      action.state = {};
    }
    if (action) actions.push(action);
  }

  // Classroom live discussions have been removed. Ignore model-emitted legacy
  // discussion actions without dropping any narration that follows them.
  const playableActions = actions.filter((action) => action.type !== 'discussion');

  // Step 6: Filter out slide-only actions for non-slide scenes (defense in depth)
  let result = playableActions;
  if (sceneType && sceneType !== 'slide') {
    const before = result.length;
    result = result.filter((a) => !SLIDE_ONLY_ACTIONS.includes(a.type as ActionType));
    if (result.length < before) {
      log.info(`Stripped ${before - result.length} slide-only action(s) from ${sceneType} scene`);
    }
  }

  // Step 7: Filter by allowedActions whitelist (defense in depth for role-based isolation)
  // Catches hallucinated actions not in the agent's permitted set, e.g. a student agent
  // mimicking spotlight/laser after seeing widget actions in chat history.
  if (allowedActions && allowedActions.length > 0) {
    const before = result.length;
    result = result.filter((a) => a.type === 'speech' || allowedActions.includes(a.type));
    if (result.length < before) {
      log.info(
        `Stripped ${before - result.length} disallowed action(s) by allowedActions whitelist`,
      );
    }
  }

  return result;
}
