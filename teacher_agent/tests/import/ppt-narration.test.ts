import { describe, expect, it } from 'vitest';
import {
  alignActionsToPptNarration,
  alignFocusActionsToSpeech,
  buildPptNarrationScripts,
} from '@/lib/import/ppt-narration';

describe('PPT narration alignment', () => {
  it('builds a page-grounded narration brief from notes and visible content', () => {
    const [script] = buildPptNarrationScripts({
      slides: [
        {
          id: 'p1',
          originalIndex: 0,
          title: '天线',
          content: '正文',
          speakerNotes: '教师讲稿。'.repeat(80),
          include: true,
        },
      ],
      revision: 1,
      updatedAt: 1,
    });
    expect(script).toContain('教师原始讲稿：教师讲稿');
    expect(script).toContain('页面可见内容：正文');
  });

  it('keeps concise model explanation and retains visual actions', () => {
    const actions = alignActionsToPptNarration(
      [
        { id: 's1', type: 'speech', text: '模型扩写一' },
        { id: 'h1', type: 'spotlight', targetIds: ['title'] },
        { id: 's2', type: 'speech', text: '模型扩写二' },
      ] as any,
      '第一页讲稿。只讲本页内容。',
    );
    expect(actions.filter((action) => action.type === 'spotlight')).toHaveLength(1);
    expect(
      actions
        .filter((action) => action.type === 'speech')
        .map((action: any) => action.text)
        .join(''),
    ).toBe('模型扩写一模型扩写二');
  });

  it('adds semantic formula meaning to the narration brief', () => {
    const [script] = buildPptNarrationScripts({
      slides: [
        {
          id: 'p1',
          originalIndex: 0,
          title: '接收功率',
          content: 'r(t) 为接收信号',
          speakerNotes: '',
          include: true,
          formulas: [String.raw`P_{RX}=\frac{1}{T}\int|r(t)|^2dt`],
          generationStrategy: 'ai-formula-enhanced',
        },
      ],
      revision: 1,
      updatedAt: 1,
    });

    expect(script).toContain(String.raw`P_{RX}=\frac{1}{T}\int|r(t)|^2dt`);
    expect(script).toContain('【公式增强页面】');
    expect(script).toContain('不要逐字符、逐运算符朗读公式');
    expect(script).toContain('解释关键物理量');
  });

  it('does not truncate a complete formula explanation at the normal 220-char limit', () => {
    const explanation =
      '先说明这个公式描述接收信号的平均功率。' +
      '其中接收功率由符号P表示，下标RX代表接收端，T表示观察时间。'.repeat(6) +
      '积分表示累计观察区间内的信号能量，再除以时间得到平均功率。';
    const actions = alignActionsToPptNarration(
      [{ id: 's1', type: 'speech', text: explanation }] as any,
      '【公式增强页面】\n本页公式（LaTeX）：P_{RX}=...',
    );
    const speech = actions.find((action) => action.type === 'speech') as any;

    expect(speech.text.length).toBeGreaterThan(220);
    expect(speech.text).toContain('积分表示累计观察区间内的信号能量');
  });

  it('keeps included-page order and excludes unchecked pages', () => {
    const scripts = buildPptNarrationScripts({
      slides: [
        {
          id: 'p1',
          originalIndex: 0,
          title: '第一页',
          content: '甲',
          speakerNotes: '',
          include: true,
        },
        {
          id: 'p2',
          originalIndex: 1,
          title: '第二页',
          content: '乙',
          speakerNotes: '',
          include: false,
        },
        {
          id: 'p3',
          originalIndex: 2,
          title: '第三页',
          content: '丙',
          speakerNotes: '第三页备注',
          include: true,
        },
      ],
      revision: 1,
      updatedAt: 1,
    });
    expect(scripts).toHaveLength(2);
    expect(scripts[0]).toContain('第一页');
    expect(scripts[1]).toContain('第三页');
    expect(scripts.join('')).not.toContain('第二页');
  });

  it('caps total speech without removing spotlight order', () => {
    const actions = alignActionsToPptNarration(
      [
        { id: 's1', type: 'speech', text: `第一句。${'深入解释'.repeat(100)}。` },
        { id: 'h1', type: 'spotlight', targetIds: ['diagram'] },
        { id: 's2', type: 'speech', text: '最后一句。' },
      ] as any,
      '本页材料',
    );
    const narration = actions
      .filter((action) => action.type === 'speech')
      .map((action: any) => action.text)
      .join('');
    expect(narration.length).toBeLessThanOrEqual(222);
    expect(actions.findIndex((action) => action.type === 'spotlight')).toBeGreaterThan(0);
  });

  it('rebinds a mismatched focus cue to the element explained next', () => {
    const actions = alignFocusActionsToSpeech(
      [
        { id: 'focus', type: 'spotlight', elementId: 'wired' },
        { id: 'speech', type: 'speech', text: '无线信道容易受到多径干扰。' },
      ] as any,
      [
        { id: 'wired', type: 'text', content: '<p>有线信道部署成本</p>' },
        { id: 'wireless', type: 'text', content: '<p>无线信道的多径干扰</p>' },
      ] as any,
    );
    expect((actions[0] as any).elementId).toBe('wireless');
  });

  it('drops a focus cue when the following explanation has no matching element', () => {
    const actions = alignFocusActionsToSpeech(
      [
        { id: 'focus', type: 'laser', elementId: 'decorative' },
        { id: 'speech', type: 'speech', text: '下面进入课堂练习。' },
      ] as any,
      [{ id: 'decorative', type: 'text', content: '<p>无线信道</p>' }] as any,
    );
    expect(actions).toEqual([{ id: 'speech', type: 'speech', text: '下面进入课堂练习。' }]);
  });
});
