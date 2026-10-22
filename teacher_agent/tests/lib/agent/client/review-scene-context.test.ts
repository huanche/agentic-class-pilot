import { describe, expect, it, vi } from 'vitest';
import { reviewSceneContext } from '@/lib/agent/client/review-scene-context';
import { makeRegenerateSceneTool } from '@/lib/agent/tools/regenerate-scene';
import type { SceneContext } from '@/lib/agent/tools/regenerate-scene-actions';

describe('teacher page review scope', () => {
  it('keeps the submitted page even when navigation selects another page later', () => {
    const context = { first: { text: 'first' }, second: { text: 'second' } };
    let selectedPage = 'first';
    const submitted = reviewSceneContext(context, selectedPage, true);
    selectedPage = 'second';
    expect(submitted).toEqual({ first: context.first });
    expect(reviewSceneContext(context, selectedPage, true)).toEqual({ second: context.second });
    expect(Object.keys(context)).toEqual(['first', 'second']);
  });

  it('refuses an out-of-page regenerate request without calling the model', async () => {
    const context = reviewSceneContext(
      { first: {} as SceneContext, second: {} as SceneContext },
      'first',
      true,
    );
    const aiCall = vi.fn();
    const tool = makeRegenerateSceneTool({ aiCall, getSceneContext: (id) => context[id] });
    const result = await tool.execute('foreign-page', { sceneId: 'second', instruction: '重做' });
    expect(result.details?.content).toBeNull();
    expect(aiCall).not.toHaveBeenCalled();
  });

  it('fails closed when the page no longer exists and preserves full-editor behavior', () => {
    const context = { first: { text: 'first' } };
    expect(reviewSceneContext(context, 'missing', true)).toEqual({});
    expect(reviewSceneContext(context, undefined, true)).toEqual({});
    expect(reviewSceneContext(context, 'first', false)).toBe(context);
  });
});
