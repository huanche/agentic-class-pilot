import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';
import type { Action } from '@openmaic/dsl';
import { approveFocusReview, fixtureTeachingPlan } from '@/tests/fixtures/focus-review';

const mocks = vi.hoisted(() => ({ generate: vi.fn(), llm: vi.fn(), build: vi.fn() }));
vi.mock('@openmaic/generation', async (original) => ({
  ...(await original<typeof import('@openmaic/generation')>()),
  generateSceneActions: mocks.generate,
  buildCompleteScene: mocks.build,
}));
vi.mock('@/lib/ai/llm', () => ({ callLLM: mocks.llm }));
vi.mock('@/lib/server/resolve-model', () => ({
  resolveModelFromRequest: async () => ({ model: {}, modelInfo: {}, modelString: 'test:model' }),
}));
import { POST } from '@/app/api/generate/scene-actions/route';

const outline = {
  id: 'o',
  type: 'slide',
  title: 'Errors',
  description: '',
  order: 1,
  durationBudget: { targetSeconds: 60 },
};
const content = {
  elements: [
    { id: 'literal', type: 'text', content: 'unterminated string literal' },
    { id: 'name', type: 'text', content: 'NameError' },
  ],
};
const actions: Action[] = [
  { id: 'f', type: 'spotlight', elementId: 'literal' },
  { id: 's', type: 'speech', text: '字符串没有结束。' },
];
function request() {
  return new NextRequest('http://localhost/api/generate/scene-actions', {
    method: 'POST',
    body: JSON.stringify({ outline, allOutlines: [outline], content, stageId: 'stage' }),
    headers: { 'content-type': 'application/json' },
  });
}
describe('scene action API enforces semantic approval before assembly', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.generate.mockResolvedValue(actions);
    mocks.build.mockImplementation((_outline, _content, finalActions) => ({
      id: 'scene',
      type: 'slide',
      content: { type: 'slide', canvas: content },
      actions: finalActions,
    }));
  });
  it('returns the reviewed paragraph/target unchanged', async () => {
    mocks.llm.mockImplementation(async (params) => ({
      text: params.system.includes('[FOCUS_SPEECH_REVIEW]')
        ? approveFocusReview(params.prompt)
        : fixtureTeachingPlan('literal', '字符串没有结束。'),
    }));
    const response = await POST(request());
    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body.scene.actions[0]).toMatchObject({ elementId: 'literal' });
    expect(body.scene.actions[1]).toMatchObject({
      text: '字符串没有结束。',
      audioInvalidated: true,
    });
    expect(mocks.generate).not.toHaveBeenCalled();
    expect(mocks.llm).toHaveBeenCalledTimes(2);
  });
  it('does not assemble or publish actions that failed both semantic checks', async () => {
    mocks.llm.mockImplementation(async (params) => ({
      text: params.system.includes('[FOCUS_SPEECH_REVIEW]')
        ? JSON.stringify({
            segments: JSON.parse(params.prompt).segments.map((s: object) => ({
              ...s,
              matches: false,
              singleTopic: false,
              reason: 'mixed topics',
            })),
          })
        : fixtureTeachingPlan('literal', '字符串没有结束。'),
    }));
    const response = await POST(request());
    expect(response.status).toBe(422);
    expect(await response.json()).toMatchObject({
      success: false,
      errorCode: 'FOCUS_SPEECH_ALIGNMENT_FAILED',
      details: expect.stringContaining('mixed topics'),
    });
    expect(mocks.generate).not.toHaveBeenCalled();
    expect(mocks.llm).toHaveBeenCalledTimes(4);
    expect(mocks.build).not.toHaveBeenCalled();
  });
});
