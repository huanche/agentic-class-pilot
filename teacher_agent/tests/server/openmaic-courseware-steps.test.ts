import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Slide } from '@openmaic/dsl';
import type { GeneratedSceneContent } from '@openmaic/generation';
import type { BackgroundCoursewareInput } from '@/lib/generation/background-courseware';
import type { SceneOutline } from '@/lib/types/generation';

const mocks = vi.hoisted(() => ({ content: vi.fn(), actions: vi.fn(), llm: vi.fn() }));
vi.mock('@openmaic/generation', async (original) => ({
  ...(await original<typeof import('@openmaic/generation')>()),
  generateSceneContent: mocks.content,
  generateSceneActions: mocks.actions,
}));
vi.mock('@/lib/server/resolve-model', () => ({
  resolveModel: async () => ({ model: {}, modelInfo: { capabilities: {} } }),
}));
vi.mock('@/lib/ai/llm', () => ({ callLLM: mocks.llm }));
vi.mock('@/lib/pbl/v2/agents/planner', () => ({ generatePBLV2Project: vi.fn() }));

import { createOpenmaicCoursewareSteps } from '@/lib/server/openmaic-courseware-steps';

const canvas: Slide = {
  id: 'source-canvas',
  elements: [],
  viewportSize: 1000,
  viewportRatio: 0.75,
  theme: { backgroundColor: '#ffffff', themeColors: [], fontColor: '#111111', fontName: 'Arial' },
};
function input(type: SceneOutline['type']): BackgroundCoursewareInput {
  return {
    sessionId: 'mixed-fidelity',
    stage: { id: 'stage', name: 'C 函数' } as BackgroundCoursewareInput['stage'],
    outlines: [
      {
        id: 'outline',
        type,
        order: 1,
        title: '函数定义',
        description: '观察调用过程',
        keyPoints: [],
        widgetType: 'simulation',
        widgetOutline: { concept: '函数调用' },
        quizConfig: { questionCount: 1, difficulty: 'easy', questionTypes: ['single'] },
        pblConfig: {
          projectTopic: '函数',
          projectDescription: '编写函数',
          targetSkills: ['函数调用'],
        },
      },
    ],
    requirements: { requirement: '根据 PPT 教学' },
    agents: [],
    preferImportedCanvas: true,
    importedSlides: [canvas],
    narrationScripts: ['原 PPT 讲稿，不应作为测验和互动的替代内容'],
    enableTTS: false,
    enableMedia: false,
  };
}

describe('high-fidelity mixed scene generation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.actions.mockResolvedValue([{ id: 'speech', type: 'speech', text: '请完成本页任务。' }]);
  });

  it('keeps the imported canvas for a regular slide', async () => {
    const selected = input('slide');
    const steps = createOpenmaicCoursewareSteps(selected, undefined, {});
    const content = await steps.content(selected.outlines[0], new AbortController().signal);
    const scene = await steps.actions(
      selected.outlines[0],
      content,
      undefined,
      new AbortController().signal,
    );
    expect(mocks.content).not.toHaveBeenCalled();
    expect(scene.content).toEqual({ type: 'slide', canvas });
  });

  it.each([
    ['interactive', { html: '<main><button>调用函数</button></main>' }],
    [
      'quiz',
      {
        questions: [
          {
            id: 'q',
            type: 'single',
            question: 'void 表示什么？',
            options: [{ value: 'A', label: '无返回值' }],
            answer: ['A'],
          },
        ],
      },
    ],
  ] satisfies [SceneOutline['type'], GeneratedSceneContent][])(
    'generates and assembles %s instead of reusing its underlying PPT canvas',
    async (type, generated) => {
      const selected = input(type);
      const steps = createOpenmaicCoursewareSteps(selected, undefined, {});
      mocks.content.mockResolvedValue(generated);
      const signal = new AbortController().signal;
      const content = await steps.content(selected.outlines[0], signal);
      expect(content).toEqual(generated);
      expect(mocks.content).toHaveBeenCalledOnce();
      const scene = await steps.actions(selected.outlines[0], content, undefined, signal);
      expect(scene.type).toBe(type);
      expect(scene.content).toMatchObject({ type, ...generated });
      expect('canvas' in scene.content).toBe(false);
    },
  );

  it('rejects a trial checkpoint with no matching answer before it is saved', async () => {
    const selected = input('quiz');
    const outline = { ...selected.outlines[0], checkpointFor: 'previous' };
    const question = {
      id: 'q1',
      type: 'single',
      question: '形参是否可以在 C 函数的定义里指定默认值？',
      options: [
        { value: 'A', label: '可以' },
        { value: 'B', label: '不可以' },
      ],
      answer: ['C'],
      analysis: 'C 函数不支持默认参数。',
    };
    mocks.content.mockResolvedValue({ questions: [question] });
    const steps = createOpenmaicCoursewareSteps(selected, undefined, {});

    await expect(steps.content(outline, new AbortController().signal)).rejects.toMatchObject({
      isRetryable: true,
    });
  });

  it('keeps one complete question when the model supplies extra trial checkpoint questions', async () => {
    const selected = input('quiz');
    const outline = { ...selected.outlines[0], checkpointFor: 'previous' };
    const question = {
      id: 'q1',
      type: 'single',
      question: 'C 函数支持默认参数吗？',
      options: [
        { value: 'A', label: '支持' },
        { value: 'B', label: '不支持' },
      ],
      answer: ['B'],
      analysis: 'C 不支持默认参数。',
    };
    mocks.content.mockResolvedValue({
      questions: [
        { ...question, id: 'invalid', answer: ['C'] },
        question,
        { ...question, id: 'q2' },
      ],
    });
    const steps = createOpenmaicCoursewareSteps(selected, undefined, {});
    await expect(steps.content(outline, new AbortController().signal)).resolves.toEqual({
      questions: [question],
    });
  });

  it.each(['invalid-model-output', 'prompt-unavailable'])(
    'classifies a missing page generated with %s',
    async (code) => {
      const selected = input('interactive');
      mocks.content.mockImplementationOnce(async (_outline, _call, options) => {
        options.onFailure({ code });
        return null;
      });
      const steps = createOpenmaicCoursewareSteps(selected, undefined, {});
      const work = steps.content(selected.outlines[0], new AbortController().signal);
      if (code === 'invalid-model-output') {
        await expect(work).rejects.toMatchObject({ isRetryable: true });
      } else {
        await expect(work).rejects.toThrow('未生成页面内容');
      }
    },
  );

  it('routes a PBL page through content generation rather than the source canvas', async () => {
    const selected = input('pbl');
    const generated = { projectV2: { title: '函数练习' } };
    mocks.content.mockResolvedValue(generated);
    const steps = createOpenmaicCoursewareSteps(selected, undefined, {});
    expect(await steps.content(selected.outlines[0], new AbortController().signal)).toEqual(
      generated,
    );
    expect(mocks.content).toHaveBeenCalledOnce();
  });

  it('requires numbered narration to follow each original click', async () => {
    const selected = input('slide');
    selected.stage.coursewareTrial = { mode: 'faithful', overview: '掌握数组边界' };
    selected.stage.nativePptx = {
      version: 1,
      pages: { outline: 5 },
      sha256: 'hash',
      sourceSha256: 'source',
      compatibility: { converted: 1, unresolved: 0 },
      clicks: {
        outline: [
          {
            id: 'onlyoffice-click-1',
            description: '显示案例',
            durationMs: 500,
            sourceEffectIds: [],
          },
          {
            id: 'onlyoffice-click-2',
            description: '移出案例后显示正文',
            durationMs: 1,
            sourceEffectIds: [],
          },
        ],
      },
    };
    selected.outlines[0].learningRequirement = 'master';
    const steps = createOpenmaicCoursewareSteps(selected, undefined, {});
    const signal = new AbortController().signal;
    const content = await steps.content(selected.outlines[0], signal);
    mocks.actions.mockResolvedValueOnce([{ id: 'a', type: 'speech', text: '[2]先讲正文' }]);
    await expect(steps.actions(selected.outlines[0], content, undefined, signal)).rejects.toThrow(
      '原稿动画步骤不一致',
    );
    mocks.actions.mockResolvedValueOnce([
      { id: 'a', type: 'speech', text: '[1]先观察案例' },
      { id: 'b', type: 'speech', text: '[2]现在看正文' },
    ]);
    const scene = await steps.actions(selected.outlines[0], content, undefined, signal);
    expect(
      scene.actions?.map((action) => (action.type === 'speech' ? action.text : action.id)),
    ).toEqual([
      'source-onlyoffice-click-1',
      '先观察案例',
      'source-onlyoffice-click-2',
      '现在看正文',
    ]);
    expect(mocks.actions.mock.calls.at(-1)?.[0].description).toContain('本小节学习要求：掌握');
  });

  it.each(['learning-skills-enhanced', 'faithful'] as const)(
    'uses the OpenMAIC actions template to generate final spoken words in %s trial mode',
    async (mode) => {
      const { generateSceneActions } =
        await vi.importActual<typeof import('@openmaic/generation')>('@openmaic/generation');
      const selected = input('slide');
      selected.stage.coursewareTrial = { mode, overview: '理解数组下标与返回值' };
      selected.stage.languageDirective = '使用中文授课。';
      const outline = selected.outlines[0];
      outline.description = '结合最终画面解释 return a[i]';
      const spoken = '看这一行。函数返回数组 a 中下标为 i 的那个元素。';
      mocks.actions.mockImplementationOnce(generateSceneActions);
      mocks.llm.mockResolvedValueOnce({
        text: JSON.stringify([{ type: 'text', content: spoken }]),
      });

      const steps = createOpenmaicCoursewareSteps(selected, undefined, {});
      const signal = new AbortController().signal;
      const content = await steps.content(outline, signal);
      const scene = await steps.actions(outline, content, undefined, signal);

      expect(mocks.llm).toHaveBeenCalledOnce();
      expect(mocks.llm).toHaveBeenCalledWith(
        expect.objectContaining({
          system: expect.stringContaining(
            'The same words will be used for voice synthesis and captions.',
          ),
          prompt: expect.stringContaining('结合最终画面解释 return a[i]'),
        }),
        'scene-actions',
        undefined,
        undefined,
      );
      expect(scene.actions).toEqual([expect.objectContaining({ type: 'speech', text: spoken })]);
    },
  );

  it('retries a trial slide with empty model actions instead of reading the outline aloud', async () => {
    const { generateSceneActions } =
      await vi.importActual<typeof import('@openmaic/generation')>('@openmaic/generation');
    const selected = input('slide');
    selected.stage.coursewareTrial = { mode: 'learning-skills-enhanced', overview: '理解函数' };
    const [outline] = selected.outlines;
    mocks.actions.mockImplementationOnce(generateSceneActions);
    mocks.llm.mockResolvedValueOnce({ text: '[]' }).mockResolvedValueOnce({ text: '[]' });
    const steps = createOpenmaicCoursewareSteps(selected, undefined, {});
    const signal = new AbortController().signal;
    const content = await steps.content(outline, signal);

    await expect(steps.actions(outline, content, undefined, signal)).rejects.toThrow(
      'The slide needs spoken narration',
    );
    expect(mocks.llm).toHaveBeenCalledTimes(2);
  });
});
