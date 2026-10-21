import { describe, expect, it } from 'vitest';
import type { Action } from '@openmaic/dsl';
import {
  applyNarrationRevisions,
  createNarrationPace,
  estimateNarrationSeconds,
  narrationUnits,
} from '@/lib/generation/narration-budget';
import { withNarrationDuration } from '@/lib/generation/course-duration';

const original: Action[] = [
  { id: 'focus', type: 'spotlight', elementId: 'region' },
  { id: 'first', type: 'speech', text: '解释本区域。', audioId: 'old-audio' },
  { id: 'last', type: 'speech', text: '接下来继续学习。' },
];

describe('narration planning before full audio synthesis', () => {
  it('counts spoken units instead of equating Latin code characters with Chinese syllables', () => {
    expect(narrationUnits('变量')).toBe(2);
    expect(narrationUnits('FFT')).toBeCloseTo(1);
    expect(narrationUnits('12。')).toBeCloseTo(2.3);
    expect(narrationUnits('   \n')).toBe(0);
  });
  it('learns only real normal-speed audio and never mixes voice identities', () => {
    const p = createNarrationPace();
    expect(p.estimate()).toBeUndefined();
    const text = '有效讲解'.repeat(10);
    p.observe({ identity: 'voice-a', text, seconds: 8 });
    p.observe({ identity: 'voice-a', text, seconds: 8 });
    expect(p.estimate()).toEqual({ unitsPerSecond: 5, samples: 1 });
    p.observe({ identity: 'voice-a', text: text + '扩展', seconds: 9, speed: 2 });
    p.observe({ identity: 'voice-a', text, seconds: NaN });
    expect(p.estimate()?.samples).toBe(1);
    p.observe({ identity: 'voice-b', text, seconds: 10 });
    expect(p.estimate()).toEqual({ unitsPerSecond: 4, samples: 1 });
    expect(p.durations([{ id: 'speech', type: 'speech', text }])).toEqual({ speech: 10 });
  });
  it('preserves measured segment durations and accounts for real reveal time', () => {
    const actions: Action[] = [
      { id: 'r', type: 'reveal', elementId: 'x', duration: 520, effect: 'fade-up' },
      { id: 's', type: 'speech', text: '汉'.repeat(50) },
    ];
    const pace = { unitsPerSecond: 5, samples: 2 };
    expect(estimateNarrationSeconds(actions, pace)).toBeCloseTo(10.52);
    expect(estimateNarrationSeconds(actions, pace, { s: 8 })).toBeCloseTo(8.52);
    expect(
      estimateNarrationSeconds([{ id: 'v', type: 'play_video', elementId: 'v' }], pace),
    ).toBeUndefined();
  });
  it('provides sampled-length guidance without claiming that estimates are measured audio', () => {
    const outline = {
      id: 'x',
      title: 'x',
      type: 'slide' as const,
      order: 1,
      description: '',
      keyPoints: [],
      durationBudget: { targetSeconds: 60 },
    };
    const text = withNarrationDuration(outline, undefined, {
      unitsPerSecond: 5,
      samples: 2,
    }).description;
    expect(text).toContain('300 个可朗读单位');
    expect(text).toContain('最终仍以音频实测为准');
    expect(text).not.toContain('中文约 210 字');
    expect(withNarrationDuration(outline).description).toContain('中文约 210 字');
  });
  it('changes only allowed text while preserving every cue and untargeted paragraph', () => {
    const candidate = applyNarrationRevisions(
      original,
      JSON.stringify({ revisions: [{ speechId: 'first', text: '本区域更完整的解释。' }] }),
      ['first'],
    );
    expect(candidate[0]).toEqual(original[0]);
    expect(candidate[1]).toMatchObject({
      id: 'first_revision',
      text: '本区域更完整的解释。',
      audioInvalidated: true,
    });
    expect(candidate[1]).not.toHaveProperty('audioId');
    expect(candidate[2]).toMatchObject({ text: '接下来继续学习。' });
    expect(original[1]).toMatchObject({ audioId: 'old-audio', text: '解释本区域。' });
  });
  it.each([
    { revisions: [{ speechId: 'last', text: '改写不允许的过渡。' }] },
    { revisions: [{ speechId: 'focus', text: '修改动作' }] },
    { revisions: [{ speechId: 'first', text: '' }] },
    {
      revisions: [
        { speechId: 'first', text: '甲' },
        { speechId: 'first', text: '乙' },
      ],
    },
    { revisions: [{ speechId: 'first', text: '甲', speed: 2 }] },
    { revisions: [], actions: [] },
  ])('rejects an invalid patch without mutating the accepted draft: %j', (response) => {
    expect(() => applyNarrationRevisions(original, JSON.stringify(response), ['first'])).toThrow();
    expect(original[1]).toMatchObject({ text: '解释本区域。' });
  });
});
