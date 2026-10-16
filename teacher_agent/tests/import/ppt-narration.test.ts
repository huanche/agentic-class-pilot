import { describe, expect, it } from 'vitest';
import {
  alignActionsToPptNarration,
  alignFocusActionsToSpeech,
  buildPptNarrationScripts,
} from '@/lib/import/ppt-narration';

describe('PPT narration alignment', () => {
  it('preserves each generated speech boundary around focus and reveal cues', () => {
    const first = '第一步打开 python.org。选择稳定版。下载完成后再安装。';
    const second = '第二步勾选 Add Python to PATH，然后点击 Install Now。';
    const input = [
      { id: 'f1', type: 'spotlight', elementId: 'download' },
      { id: 's1', type: 'speech', text: first },
      { id: 'r', type: 'reveal', elementId: 'install' },
      { id: 'f2', type: 'spotlight', elementId: 'install' },
      { id: 's2', type: 'speech', text: second },
    ] as Parameters<typeof alignActionsToPptNarration>[0];
    for (const preserveGeneratedLength of [true, false]) {
      const output = alignActionsToPptNarration(input, undefined, [], { preserveGeneratedLength });
      expect(
        output.filter((action) => action.type === 'speech').map((action) => action.text),
      ).toEqual([first, second]);
      expect(output.map((action) => action.id)).toEqual(input.map((action) => action.id));
    }
  });

  it('keeps the full generated narration when a measured duration budget is in use', () => {
    const longText = '这是按教师时长预算生成的完整讲解，包含必要的解释与示例。'.repeat(40);
    const actions = alignActionsToPptNarration(
      [
        { id: 'a', type: 'speech', text: longText },
        { id: 'r', type: 'reveal', elementId: 'conclusion' },
      ],
      undefined,
      [],
      { preserveGeneratedLength: true },
    );
    expect(
      actions
        .filter((action) => action.type === 'speech')
        .map((action) => action.text)
        .join(''),
    ).toBe(longText);
    expect(actions.at(-1)?.type).toBe('reveal');
  });
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
        { id: 'h1', type: 'spotlight', elementId: 'title' },
        { id: 's2', type: 'speech', text: '模型扩写二' },
      ],
      '第一页讲稿。只讲本页内容。',
    );
    expect(actions.filter((action) => action.type === 'spotlight')).toHaveLength(1);
    expect(
      actions
        .filter((action) => action.type === 'speech')
        .map((action) => action.text)
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
      [{ id: 's1', type: 'speech', text: explanation }],
      '【公式增强页面】\n本页公式（LaTeX）：P_{RX}=...',
    );
    const speech = actions.find((action) => action.type === 'speech')!;

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

  it('caps legacy narration within the original speech slots instead of moving sentences to later targets', () => {
    const first = `第一句。${'深入解释'.repeat(100)}。`;
    const actions = alignActionsToPptNarration(
      [
        { id: 'h1', type: 'spotlight', elementId: 'first' },
        { id: 's1', type: 'speech', text: first },
        { id: 'h2', type: 'spotlight', elementId: 'last' },
        { id: 's2', type: 'speech', text: '最后一句。' },
      ],
      '本页材料',
      [
        { id: 'first', type: 'text', content: '深入解释' },
        { id: 'last', type: 'text', content: '最后一句' },
      ] as unknown as Parameters<typeof alignActionsToPptNarration>[2],
    );
    const narration = actions
      .filter((action) => action.type === 'speech')
      .map((action) => action.text)
      .join('');
    expect(narration.length).toBeLessThanOrEqual(222);
    expect(actions.map((action) => action.id)).toEqual(['h1', 's1']);
    expect(actions.find((action) => action.id === 's1')).toMatchObject({
      text: expect.stringContaining('第一句。'),
    });
  });

  it('leaves semantic mismatch detection to the generation gate rather than guessing another target', () => {
    const actions = alignFocusActionsToSpeech(
      [
        { id: 'focus', type: 'spotlight', elementId: 'wired' },
        { id: 'speech', type: 'speech', text: '无线信道容易受到多径干扰。' },
      ],
      [
        { id: 'wired', type: 'text', content: '<p>有线信道部署成本</p>' },
        { id: 'wireless', type: 'text', content: '<p>无线信道的多径干扰</p>' },
      ] as unknown as Parameters<typeof alignFocusActionsToSpeech>[1],
    );
    expect(actions[0]).toMatchObject({ elementId: 'wired' });
  });

  it('drops orphaned visual cues instead of pairing them with an earlier speech', () => {
    const actions = alignFocusActionsToSpeech(
      [
        { id: 's', type: 'speech', text: '本页讲解已结束。' },
        { id: 'f', type: 'spotlight', elementId: 'late' },
      ],
      [],
    );
    expect(actions.map((action) => action.id)).toEqual(['s']);
  });
});
