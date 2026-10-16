import { describe, expect, it } from 'vitest';
import type { PPTElement } from '@openmaic/dsl';
import { compileTeachingPlan } from '@/lib/generation/teaching-plan';
import { inspectSpeechFocus } from '@/lib/generation/speech-focus-contract';

const elements = [
  { id: 'error', type: 'text', content: 'SyntaxError 引号未闭合' },
  { id: 'answer', type: 'text', content: '补齐引号' },
  { id: 'movie', type: 'video', src: '/demo.mp4' },
] as PPTElement[];
const explain = (targetId: string | null, speech = '引号未闭合。') => ({
  kind: 'narration',
  purpose: 'explanation',
  targetId,
  speech,
});
function compile(segments: unknown[]) {
  return compileTeachingPlan(JSON.stringify({ segments }), elements, ['student'], 'test');
}

describe('atomic teaching plan compilation', () => {
  it('rejects ambiguous slide element IDs instead of binding to the last duplicate', () => {
    const result = compileTeachingPlan(
      JSON.stringify({ segments: [explain('error')] }),
      [elements[0], elements[0]],
      [],
      'test',
    );
    expect(result.actions).toEqual([]);
    expect(result.issues.join()).toContain('unique');
  });
  it('keeps a target and exact narration together, including repeated paragraphs on one target', () => {
    const result = compile([explain('error'), explain('error', '请检查字符串末尾的引号。')]);
    expect(result.issues).toEqual([]);
    expect(inspectSpeechFocus(result.actions, elements).segments).toMatchObject([
      { text: '引号未闭合。', targetIds: ['error'] },
      { text: '请检查字符串末尾的引号。', targetIds: ['error'] },
    ]);
  });
  it('compiles a delayed conclusion as reveal, focus, speech without changing its words', () => {
    const result = compile([
      explain('error'),
      { ...explain('answer', '补齐引号。'), revealBefore: true, focus: 'laser' },
    ]);
    expect(result.issues).toEqual([]);
    expect(result.actions.map((a) => a.type)).toEqual([
      'spotlight',
      'speech',
      'reveal',
      'laser',
      'speech',
    ]);
    expect(inspectSpeechFocus(result.actions, elements).issues).toEqual([]);
    expect(new Set(result.actions.map((a) => a.id)).size).toBe(result.actions.length);
  });
  it.each([
    explain(null),
    { ...explain(null), purpose: ['explanation'] },
    explain('missing'),
    { kind: 'narration', purpose: 'explanation', speech: '没有目标字段。' },
    { ...explain('error'), targetId: ['error', 'answer'] },
    { ...explain('error'), speech: '' },
    { ...explain('error'), revealBefore: 'false' },
    { ...explain(null), purpose: 'opening', revealBefore: true },
    { ...explain('error'), audioId: 'stale' },
  ])('rejects invalid or missing bindings instead of guessing: %j', (segment) => {
    const result = compile([segment]);
    expect(result.issues.length).toBeGreaterThan(0);
    expect(result.actions).toEqual([]);
  });
  it('allows an explicitly unfocused opening but never carries the last focus into it', () => {
    const result = compile([
      explain('error'),
      { kind: 'narration', purpose: 'transition', targetId: null, speech: '接下来看另一个例子。' },
    ]);
    expect(result.issues).toEqual([]);
    expect(inspectSpeechFocus(result.actions, elements).segments[1].targetIds).toEqual([]);
  });
  it('preserves video order and a final discussion without accepting arbitrary action objects', () => {
    const result = compile([
      { kind: 'narration', purpose: 'transition', targetId: null, speech: '来看演示。' },
      { kind: 'video', targetId: 'movie' },
      explain('error'),
      { kind: 'discussion', topic: '如何排查？', agentId: 'student' },
    ]);
    expect(result.issues).toEqual([]);
    expect(result.actions.map((a) => a.type)).toEqual([
      'speech',
      'play_video',
      'spotlight',
      'speech',
      'discussion',
    ]);
    expect(compile([{ kind: 'video', targetId: 'error' }]).issues.length).toBeGreaterThan(0);
    expect(compile([{ kind: 'discussion', topic: '问题' }, explain('error')]).actions).toEqual([]);
    expect(compile([{ kind: 'discussion', topic: '问题', agentId: 'unknown' }]).actions).toEqual(
      [],
    );
    expect(compile([{ type: 'spotlight', elementId: 'error' }]).actions).toEqual([]);
  });
  it('rejects a target used before its planned reveal and duplicate reveals', () => {
    expect(
      compile([explain('answer'), { ...explain('answer'), revealBefore: true }]).actions,
    ).toEqual([]);
    expect(
      compile([
        { ...explain('answer'), revealBefore: true },
        { ...explain('answer'), revealBefore: true },
      ]).actions,
    ).toEqual([]);
  });
  it('rejects malformed or legacy loose actions rather than fabricating a default speech', () => {
    for (const input of ['{', '[]', '{}', '{"segments":[]}']) {
      expect(compileTeachingPlan(input, elements, [], 'test').actions).toEqual([]);
      expect(compileTeachingPlan(input, elements, [], 'test').issues.length).toBeGreaterThan(0);
    }
  });
});
