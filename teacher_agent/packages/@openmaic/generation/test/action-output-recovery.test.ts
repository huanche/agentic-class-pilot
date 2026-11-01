import { describe, expect, it, vi } from 'vitest';
import { validateAction, validateScene } from '@openmaic/dsl';
import {
  buildCompleteScene,
  generateSceneActions,
  parseActionsFromStructuredOutput,
  withGenerationRetry,
  type AICallFn,
  type GeneratedInteractiveContent,
  type GeneratedQuizContent,
} from '@openmaic/generation';
import { quizOutline, slideOutline, widgetOutline } from './scene-fixtures.js';

const speech = '先声明变量，再观察程序的执行结果。';
const slideContent = { elements: [] };
const structuredSpeech = { type: 'text', content: speech };

describe('model action output normalization', () => {
  it.each([
    { type: 'text', content: speech },
    { type: 'text', text: speech },
    { type: 'speech', text: speech },
    { type: 'action', name: 'text', params: { content: speech } },
    { type: 'action', name: 'text', params: { text: speech } },
    { type: 'action', name: 'speech', params: { content: speech } },
    { type: 'action', tool_name: 'text', parameters: { content: speech } },
  ])('preserves narration from %j as a playable speech action', (item) => {
    const actions = parseActionsFromStructuredOutput(JSON.stringify([item]), 'slide');
    expect(actions).toEqual([expect.objectContaining({ type: 'speech', text: speech })]);
    expect(validateAction(actions[0])).toEqual({ valid: true });
  });

  it('prevents parameters from overriding the action type or identity', () => {
    const actions = parseActionsFromStructuredOutput(
      JSON.stringify([
        {
          type: 'action',
          action_id: 'authored-cue',
          name: 'spotlight',
          params: { id: 'wrong-id', type: 'text', elementId: 'code-example' },
        },
        { type: 'action', name: 'speech', params: { type: 'text', text: speech } },
      ]),
      'slide',
    );
    expect(actions[0]).toMatchObject({
      id: 'authored-cue',
      type: 'spotlight',
      elementId: 'code-example',
    });
    expect(actions[1]).toMatchObject({ type: 'speech', text: speech });
    expect(actions.every((action) => validateAction(action).valid)).toBe(true);
  });

  it('fixes the exact nineteenth-action validation failure without deleting narration', async () => {
    const output = [
      ...Array.from({ length: 18 }, () => structuredSpeech),
      { type: 'action', name: 'text', params: { content: '最后检查变量的值。' } },
    ];
    const call = vi.fn(async () => JSON.stringify(output));
    const outline = slideOutline();
    const actions = await generateSceneActions(outline, slideContent, call);
    const scene = buildCompleteScene(outline, slideContent, actions, 'stage');
    expect(actions).toHaveLength(19);
    expect(actions[18]).toMatchObject({ type: 'speech', text: '最后检查变量的值。' });
    expect(validateScene(scene)).toEqual({ valid: true });
    expect(call).toHaveBeenCalledOnce();
  });
});

describe('bounded current-page action format recovery', () => {
  it.each([
    { type: 'action', name: 'unknown_action', params: {} },
    { type: 'action', name: 'laser', params: {} },
    { type: 'action', name: 'text', params: { content: 42 } },
    { type: 'text', content: { text: speech } },
    { type: 'action', name: 'speech', params: [speech] },
  ])('repairs invalid output %j with one extra action request', async (invalid) => {
    const call = vi
      .fn<AICallFn>()
      .mockResolvedValueOnce(JSON.stringify([structuredSpeech, invalid]))
      .mockResolvedValueOnce(JSON.stringify([structuredSpeech]));
    const actions = await generateSceneActions(slideOutline(), slideContent, call);
    expect(actions).toEqual([expect.objectContaining({ type: 'speech', text: speech })]);
    expect(call).toHaveBeenCalledTimes(2);
    const [system, original] = call.mock.calls[0];
    const [retrySystem, retryPrompt] = call.mock.calls[1];
    expect(retrySystem).toBe(system);
    expect(retryPrompt).toContain(original);
    expect(retryPrompt).toContain('Action format correction');
    expect(retryPrompt).toContain('complete action array');
  });

  it('does not mask persistent invalid output with a generic fallback lecture', async () => {
    const call = vi
      .fn<AICallFn>()
      .mockResolvedValue(JSON.stringify([{ type: 'action', name: 'unknown_action', params: {} }]));
    await expect(generateSceneActions(slideOutline(), slideContent, call)).rejects.toThrow(
      /已自动重试 1 次.*unknown action type/,
    );
    expect(call).toHaveBeenCalledTimes(2);
  });

  it('rejects an empty correction instead of replacing the page narration with an overview', async () => {
    const call = vi
      .fn<AICallFn>()
      .mockResolvedValueOnce(
        JSON.stringify([structuredSpeech, { type: 'action', name: 'unknown_action', params: {} }]),
      )
      .mockResolvedValueOnce('[]');
    await expect(generateSceneActions(slideOutline(), slideContent, call)).rejects.toThrow(
      /已自动重试 1 次.*empty action array/,
    );
    expect(call).toHaveBeenCalledTimes(2);
  });

  it('does not multiply format attempts inside the outer provider retry loop', async () => {
    const call = vi
      .fn<AICallFn>()
      .mockResolvedValue(
        JSON.stringify([{ type: 'action', name: 'timeout_unknown_action', params: {} }]),
      );
    const sleep = vi.fn(async () => {});
    await expect(
      withGenerationRetry(() => generateSceneActions(slideOutline(), slideContent, call), {
        label: 'current page actions',
        maxRetries: 5,
        sleep,
      }),
    ).rejects.toThrow('已自动重试 1 次');
    expect(call).toHaveBeenCalledTimes(2);
    expect(sleep).not.toHaveBeenCalled();
  });

  it.each([
    Object.assign(new Error('Unauthorized'), { status: 401 }),
    Object.assign(new Error('Cancelled'), { name: 'AbortError' }),
    new Error('network unavailable'),
  ])('propagates provider and cancellation failures without a format retry', async (error) => {
    const call = vi.fn<AICallFn>().mockRejectedValue(error);
    await expect(generateSceneActions(slideOutline(), slideContent, call)).rejects.toBe(error);
    expect(call).toHaveBeenCalledOnce();
  });

  it('applies the same recovery to quiz and interactive narration', async () => {
    const quiz: GeneratedQuizContent = { questions: [] };
    const interactive: GeneratedInteractiveContent = {
      html: '<div id="result"></div>',
      widgetType: 'simulation',
    };
    for (const [outline, content] of [
      [quizOutline(), quiz],
      [widgetOutline(), interactive],
    ] as const) {
      const call = vi
        .fn<AICallFn>()
        .mockResolvedValueOnce(
          JSON.stringify([
            structuredSpeech,
            { type: 'action', name: 'text', params: { content: null } },
          ]),
        )
        .mockResolvedValueOnce(JSON.stringify([structuredSpeech]));
      const actions = await generateSceneActions(outline, content, call);
      expect(actions).toEqual([expect.objectContaining({ type: 'speech', text: speech })]);
      expect(call).toHaveBeenCalledTimes(2);
    }
  });
});
