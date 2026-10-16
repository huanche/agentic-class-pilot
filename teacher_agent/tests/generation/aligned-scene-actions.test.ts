import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { PPTElement } from '@openmaic/dsl';
import { generateSceneActions } from '@openmaic/generation';
import {
  generateAlignedSceneActions,
  FocusSpeechAlignmentError,
} from '@/lib/server/aligned-scene-actions';
import { inspectSpeechFocus, teachingInventory } from '@/lib/generation/speech-focus-contract';
import { approveFocusReview } from '@/tests/fixtures/focus-review';
vi.mock('@openmaic/generation', () => ({ generateSceneActions: vi.fn() }));
const outline = {
  id: 'page',
  type: 'slide' as const,
  title: 'Python 报错',
  description: '',
  keyPoints: [],
  order: 1,
};
const content = {
  elements: [
    {
      id: 'literal',
      type: 'text',
      content: 'SyntaxError unterminated string literal (detected at line 1)',
    },
    { id: 'name', type: 'text', content: 'NameError 名称错误' },
    {
      id: 'tools',
      type: 'table',
      data: [
        [{ text: 'IDLE' }, { text: '零配置，界面简陋' }],
        [{ text: 'VS Code' }, { text: '插件丰富，需装 Python 扩展' }],
      ],
    },
  ] as PPTElement[],
};
const segment = (targetId = 'literal', speech = '字符串没有结束。') => ({
  kind: 'narration',
  purpose: 'explanation',
  targetId,
  speech,
});
const plan = (...segments: unknown[]) => JSON.stringify({ segments });
const isReview = (system: string) => system.includes('[FOCUS_SPEECH_REVIEW]');
describe('generation-time atomic teaching plan and semantic gate', () => {
  it('never sends a malformed slide through an unchecked legacy path', async () => {
    const ai = vi.fn();
    await expect(
      generateAlignedSceneActions(outline, { questions: [] }, ai),
    ).rejects.toBeInstanceOf(FocusSpeechAlignmentError);
    expect(ai).not.toHaveBeenCalled();
  });
  beforeEach(() => vi.mocked(generateSceneActions).mockReset());
  it('repairs cross-topic narration as separate target/text units using the actual previous plan', async () => {
    let attempts = 0;
    const wrong = plan(segment('name', '没结束的字符串。第二个，NameError，名称错误。'));
    const generate = vi.fn(async (system: string, user: string) => {
      if (!isReview(system))
        return ++attempts === 1 ? wrong : plan(segment(), segment('name', '名称没有定义。'));
      const data = JSON.parse(user);
      if (attempts === 1)
        return JSON.stringify({
          segments: data.segments.map((s: object) => ({
            ...s,
            matches: false,
            singleTopic: false,
            reason: '字符串和名称错误必须拆段',
          })),
        });
      return approveFocusReview(user);
    });
    const result = await generateAlignedSceneActions(outline, content, generate);
    expect(inspectSpeechFocus(result, content.elements).segments).toMatchObject([
      { text: '字符串没有结束。', targetIds: ['literal'] },
      { text: '名称没有定义。', targetIds: ['name'] },
    ]);
    expect(generate).toHaveBeenCalledTimes(4);
    const repair = JSON.parse(generate.mock.calls[2][1]);
    expect(repair.previousCandidate).toBe(wrong);
    expect(repair.issues.join()).toContain('必须拆段');
    expect(generateSceneActions).not.toHaveBeenCalled();
  });
  it('rejects missing targets before review and then compiles a valid binding', async () => {
    let attempts = 0;
    const ai = vi.fn(async (system: string, user: string) =>
      isReview(system)
        ? approveFocusReview(user)
        : ++attempts === 1
          ? plan({ ...segment(), targetId: null })
          : plan(segment()),
    );
    const result = await generateAlignedSceneActions(outline, content, ai);
    expect(ai).toHaveBeenCalledTimes(3);
    expect(result[0]).toMatchObject({ type: 'spotlight', elementId: 'literal' });
    expect(JSON.parse(ai.mock.calls[1][1]).issues.join()).toContain('requires its own targetId');
  });
  it('provides full table evidence, language, duration and course context', async () => {
    const ai = vi.fn(async (system: string, user: string) =>
      isReview(system)
        ? approveFocusReview(user)
        : plan(segment('tools', 'IDLE 零配置；VS Code 要安装扩展。')),
    );
    await generateAlignedSceneActions({ ...outline, description: '目标讲解 60 秒' }, content, ai, {
      languageDirective: '简体中文',
      userProfile: '初学者',
      ctx: {
        pageIndex: 2,
        totalPages: 3,
        allTitles: ['A', 'B', 'C'],
        previousSpeeches: ['刚刚讲完安装。'],
      },
    });
    expect(ai.mock.calls[0][1]).toContain('目标讲解 60 秒');
    expect(ai.mock.calls[0][1]).toContain('刚刚讲完安装');
    for (const [, user] of ai.mock.calls) {
      expect(user).toContain('插件丰富，需装 Python 扩展');
      expect(user).toContain('简体中文');
    }
  });
  it.each([
    '{}',
    '{"segments":[]}',
    '{"segments":[{"speechId":"other","targetIds":[],"matches":true,"singleTopic":true}]}',
  ])('rejects incomplete approval: %s', async (review) => {
    const ai = vi.fn(async (system: string) => (isReview(system) ? review : plan(segment())));
    await expect(generateAlignedSceneActions(outline, content, ai)).rejects.toMatchObject({
      name: 'FocusSpeechAlignmentError',
      statusCode: 422,
      isRetryable: false,
    });
    expect(ai).toHaveBeenCalledTimes(4);
  });
  it('never falls back to loose actions or unchecked default narration', async () => {
    const ai = vi.fn(async () => '[{"type":"text","content":"Fallback"}]');
    await expect(generateAlignedSceneActions(outline, content, ai)).rejects.toBeInstanceOf(
      FocusSpeechAlignmentError,
    );
    expect(ai).toHaveBeenCalledTimes(2);
    expect(generateSceneActions).not.toHaveBeenCalled();
  });
  it('reviews the final transformed text, removes stale audio and preserves its target', async () => {
    const ai = vi.fn(async (system: string, user: string) =>
      isReview(system) ? approveFocusReview(user) : plan(segment()),
    );
    const actions = await generateAlignedSceneActions(outline, content, ai, {
      transformActions: (actions) =>
        actions.map((a) =>
          a.type === 'speech'
            ? { ...a, text: '最终讲稿。', audioId: 'old', audioUrl: 'old.wav', audioRef: 'old.wav' }
            : a,
        ),
    });
    expect(JSON.parse(ai.mock.calls[1][1]).segments[0]).toMatchObject({
      text: '最终讲稿。',
      targetIds: ['literal'],
    });
    expect(actions[1]).toMatchObject({ text: '最终讲稿。', audioInvalidated: true });
    for (const key of ['audioId', 'audioUrl', 'audioRef'])
      expect(actions[1]).not.toHaveProperty(key);
  });
  it('does not retry provider cancellation as a content repair', async () => {
    const canceled = new DOMException('Canceled', 'AbortError');
    const ai = vi.fn(async (system: string) => {
      if (isReview(system)) throw canceled;
      return plan(segment());
    });
    await expect(generateAlignedSceneActions(outline, content, ai)).rejects.toBe(canceled);
    expect(ai).toHaveBeenCalledTimes(2);
  });
  it('keeps quizzes and widgets on their existing generator path', async () => {
    vi.mocked(generateSceneActions).mockResolvedValue([
      { id: 's', type: 'speech', text: '请作答。' },
    ]);
    const ai = vi.fn();
    await generateAlignedSceneActions({ ...outline, type: 'quiz' }, { questions: [] }, ai);
    expect(generateSceneActions).toHaveBeenCalledOnce();
    expect(ai).not.toHaveBeenCalled();
  });
  it('includes chart data and shape text in evidence', () => {
    const evidence = teachingInventory([
      {
        id: 'chart',
        type: 'chart',
        chartType: 'bar',
        data: { labels: ['A', 'B'], series: ['人数'], values: [[3, 8]] },
      },
      { id: 'shape', type: 'shape', text: { content: '<p>解释器</p>' } },
    ] as PPTElement[]);
    expect(evidence[0]).toMatchObject({ chartData: { labels: ['A', 'B'], values: [[3, 8]] } });
    expect(evidence[1].text).toContain('解释器');
  });
});
