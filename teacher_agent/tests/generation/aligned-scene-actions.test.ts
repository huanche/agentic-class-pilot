import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Action, PPTElement } from '@openmaic/dsl';
import { generateSceneActions } from '@openmaic/generation';
import { teachingInventory } from '@/lib/generation/speech-focus-contract';
import {
  generateAlignedSceneActions,
  FocusSpeechAlignmentError,
} from '@/lib/server/aligned-scene-actions';

vi.mock('@openmaic/generation', () => ({ generateSceneActions: vi.fn() }));
const generate = vi.mocked(generateSceneActions);
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
    { id: 'literal', type: 'text', content: 'unterminated string literal (detected at line 1)' },
    { id: 'name', type: 'text', content: 'NameError 名称错误' },
    {
      id: 'tools',
      type: 'table',
      data: [
        [{ text: 'IDLE' }, { text: '零配置，界面简陋' }],
        [{ text: 'VS Code' }, { text: '插件丰富，需装 Python 扩展' }],
      ],
    },
  ] as unknown as PPTElement[],
};
const pair = (id = 's', target = 'literal', text = '字符串没有结束。'): Action[] => [
  { id: `f-${id}`, type: 'spotlight', elementId: target },
  { id, type: 'speech', text },
];
function approve(user: string) {
  const input = JSON.parse(user);
  return JSON.stringify({
    segments: input.segments.map((segment: { speechId: string; targetIds: string[] }) => ({
      speechId: segment.speechId,
      targetIds: segment.targetIds,
      matches: true,
      singleTopic: true,
      reason: '',
    })),
  });
}
describe('generation-time focus/speech gate', () => {
  beforeEach(() => generate.mockReset());
  it('regenerates a mixed paragraph as separate target/speech pairs before returning a scene', async () => {
    const wrong = pair('old', 'name', '没结束的字符串。第二个，NameError，名称错误。');
    const fixed = [...pair('a'), ...pair('b', 'name', '第二个，NameError，名称错误。')];
    generate.mockResolvedValueOnce(wrong).mockResolvedValueOnce(fixed);
    const review = vi.fn(async (_system: string, user: string) => {
      const data = JSON.parse(user);
      return data.segments[0].speechId === 'old'
        ? JSON.stringify({
            segments: [
              {
                speechId: 'old',
                targetIds: ['name'],
                matches: false,
                singleTopic: false,
                reason: '字符串解释与名称错误跨越两个目标，必须拆段。',
              },
            ],
          })
        : approve(user);
    });
    const result = await generateAlignedSceneActions(outline, content, review);
    expect(result.map((action) => action.id)).toEqual(['f-a', 'a', 'f-b', 'b']);
    expect(generate).toHaveBeenCalledTimes(2);
    expect(review).toHaveBeenCalledTimes(2);
    expect(generate.mock.calls[1][0].description).toContain('必须拆段');
    expect(generate.mock.calls[1][0].description).toContain(
      '没结束的字符串。第二个，NameError，名称错误。',
    );
    expect(wrong).toEqual(pair('old', 'name', '没结束的字符串。第二个，NameError，名称错误。'));
  });
  it('includes complete table contents in both generation and review evidence', async () => {
    generate.mockResolvedValue(pair('s', 'tools', 'IDLE 零配置；VS Code 需要安装扩展。'));
    const review = vi.fn(async (_system: string, user: string) => approve(user));
    await generateAlignedSceneActions(outline, content, review);
    expect(generate.mock.calls[0][0].description).toContain('零配置，界面简陋');
    expect(review.mock.calls[0][1]).toContain('插件丰富，需装 Python 扩展');
  });

  it('makes chart values and text embedded inside shapes available to the reviewer', () => {
    const inventory = teachingInventory([
      {
        id: 'chart',
        type: 'chart',
        chartType: 'bar',
        data: { labels: ['A', 'B'], series: ['人数'], values: [[3, 8]] },
      },
      { id: 'shape', type: 'shape', text: { content: '<p>输入解释器</p>' } },
    ] as unknown as PPTElement[]);
    expect(inventory[0]).toMatchObject({ chartData: { labels: ['A', 'B'], values: [[3, 8]] } });
    expect(inventory[1].text).toContain('输入解释器');
  });
  it.each([
    '{}',
    '{"segments":[]}',
    '{"segments":[{"speechId":"other","targetIds":["literal"],"matches":true,"singleTopic":true}]}',
  ])('rejects incomplete or unrelated approval: %s', async (response) => {
    generate.mockResolvedValue(pair());
    await expect(
      generateAlignedSceneActions(outline, content, async () => response),
    ).rejects.toMatchObject({
      name: 'FocusSpeechAlignmentError',
      statusCode: 422,
      isRetryable: false,
    });
    expect(generate).toHaveBeenCalledTimes(2);
  });
  it('rejects missing ids and focus on an unrevealed element without trusting semantic approval', async () => {
    generate
      .mockResolvedValueOnce(pair('s', 'missing'))
      .mockResolvedValueOnce([...pair(), { id: 'r', type: 'reveal', elementId: 'literal' }]);
    const review = vi.fn(async (_system: string, user: string) => approve(user));
    await expect(generateAlignedSceneActions(outline, content, review)).rejects.toBeInstanceOf(
      FocusSpeechAlignmentError,
    );
    expect(review).not.toHaveBeenCalled();
  });
  it('permits reveal followed by its own focus and speech', async () => {
    generate.mockResolvedValue([{ id: 'r', type: 'reveal', elementId: 'literal' }, ...pair()]);
    const result = await generateAlignedSceneActions(outline, content, async (_system, user) =>
      approve(user),
    );
    expect(result.map((action) => action.type)).toEqual(['reveal', 'spotlight', 'speech']);
  });
  it('reviews the final postprocessed paragraphs and preserves the reviewed target', async () => {
    generate.mockResolvedValue(pair('s', 'literal', '尚未裁剪的原稿。'));
    const review = vi.fn(async (_system: string, user: string) => approve(user));
    const result = await generateAlignedSceneActions(outline, content, review, {
      transformActions: (actions) =>
        actions.map((action) =>
          action.type === 'speech' ? { ...action, text: '最终讲稿。' } : action,
        ),
    });
    expect(JSON.parse(review.mock.calls[0][1]).segments[0]).toMatchObject({
      text: '最终讲稿。',
      targetIds: ['literal'],
    });
    expect(result[0]).toMatchObject({ elementId: 'literal' });
  });
  it('clears all old audio references on newly generated speech without modifying the candidate', async () => {
    const candidate = [
      ...pair().slice(0, 1),
      {
        id: 's',
        type: 'speech',
        text: '字符串没有结束。',
        audioId: 'stale',
        audioUrl: 'https://old.invalid/a.wav',
        audioRef: 'old.wav',
      },
    ] as Action[];
    generate.mockResolvedValue(candidate);
    const result = await generateAlignedSceneActions(outline, content, async (_system, user) =>
      approve(user),
    );
    expect(result[1]).not.toHaveProperty('audioId');
    expect(result[1]).not.toHaveProperty('audioUrl');
    expect(result[1]).not.toHaveProperty('audioRef');
    expect(candidate[1]).toHaveProperty('audioId', 'stale');
  });
  it('does not retry canceled or unavailable review calls as semantic failures', async () => {
    generate.mockResolvedValue(pair());
    const canceled = new DOMException('Canceled', 'AbortError');
    await expect(
      generateAlignedSceneActions(outline, content, async () => {
        throw canceled;
      }),
    ).rejects.toBe(canceled);
    expect(generate).toHaveBeenCalledTimes(1);
  });
  it('keeps non-slide generators on their existing path', async () => {
    generate.mockResolvedValue([{ id: 's', type: 'speech', text: '请作答。' }]);
    const review = vi.fn();
    await generateAlignedSceneActions({ ...outline, type: 'quiz' }, { questions: [] }, review);
    expect(generate).toHaveBeenCalledTimes(1);
    expect(review).not.toHaveBeenCalled();
  });
});
