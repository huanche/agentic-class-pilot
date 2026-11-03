import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Slide } from '@openmaic/dsl';
import type { GeneratedSceneContent } from '@openmaic/generation';
import type { BackgroundCoursewareInput } from '@/lib/generation/background-courseware';
import type { SceneOutline } from '@/lib/types/generation';

const mocks = vi.hoisted(() => ({ content: vi.fn(), actions: vi.fn() }));
vi.mock('@openmaic/generation', async (original) => ({
  ...(await original<typeof import('@openmaic/generation')>()),
  generateSceneContent: mocks.content,
  generateSceneActions: mocks.actions,
}));
vi.mock('@/lib/server/resolve-model', () => ({
  resolveModel: async () => ({ model: {}, modelInfo: { capabilities: {} } }),
}));
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
});
