import { describe, expect, it } from 'vitest';
import { captionsForClip, captionCueText } from '@/lib/classroom-video/captions';
import type { Scene } from '@/lib/types/stage';
const scene = {
  actions: [
    { id: 'a', type: 'speech', text: '先看 a < b 的条件。' },
    { id: 'effect', type: 'laser' },
    { id: 'b', type: 'speech', text: '然后调用 print_line();' },
  ],
} as Scene;
describe('captions from the immutable recording timeline', () => {
  it('honors actual capture delays and measured audio duration, including silent actions between speeches', () => {
    expect(
      captionsForClip(scene, {
        duration: 25,
        speech: [
          { actionId: 'a', offset: 2.5, duration: 4.2 },
          { actionId: 'b', offset: 16, duration: 6 },
        ],
      }),
    ).toEqual([
      { start: 2.5, end: 6.7, text: '先看 a < b 的条件。' },
      { start: 16, end: 22, text: '然后调用 print_line();' },
    ]);
  });
  it('bounds the cue to the encoded video and rejects absent or invalid speech entries', () => {
    expect(
      captionsForClip(scene, {
        duration: 20,
        speech: [
          { actionId: 'missing', offset: 0, duration: 5 },
          { actionId: 'a', offset: -0.2, duration: 2 },
          { actionId: 'b', offset: 18, duration: 4 },
          { actionId: 'a', offset: NaN, duration: 1 },
        ],
      }),
    ).toEqual([
      { start: 0, end: 1.8, text: '先看 a < b 的条件。' },
      { start: 18, end: 20, text: '然后调用 print_line();' },
    ]);
  });
  it('keeps long narration readable while retaining the measured speech interval', () => {
    const text =
      '同学们好，欢迎来到C语言程序设计课堂。从这一页起，我们正式进入第8章——函数。先来看看函数的用途。';
    const cues = captionsForClip({ actions: [{ id: 's', type: 'speech', text }] } as Scene, {
      duration: 20,
      speech: [{ actionId: 's', offset: 2, duration: 16 }],
    });
    expect(cues.length).toBeGreaterThan(1);
    expect(cues.map((c) => c.text).join('')).toBe(text);
    expect(cues.every((c) => Array.from(c.text).length <= 32)).toBe(true);
    expect(cues[0].start).toBe(2);
    expect(cues.at(-1)?.end).toBe(18);
    for (let n = 1; n < cues.length; n++) expect(cues[n].start).toBe(cues[n - 1].end);
  });
  it('keeps C code and markup-like text literal in native cues', () => {
    expect(captionCueText('a < b && b > 0; <i>内容</i>')).toBe(
      'a &lt; b &amp;&amp; b &gt; 0; &lt;i&gt;内容&lt;/i&gt;',
    );
  });
});
