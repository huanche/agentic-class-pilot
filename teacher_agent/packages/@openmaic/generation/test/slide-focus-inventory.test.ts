import { describe, expect, it, vi } from 'vitest';
import type { GeneratedSlideContent } from '@openmaic/generation';
import { generateSceneActions } from '@openmaic/generation';
import { slideOutline } from './scene-fixtures.js';

const content: GeneratedSlideContent = {
  elements: [
    {
      id: 'master-decoration',
      type: 'shape',
      left: 20,
      top: 10,
      width: 40,
      height: 20,
      text: { content: '' },
    },
    {
      id: 'compound-example',
      type: 'shape',
      left: 500,
      top: 220,
      width: 380,
      height: 200,
      text: {
        content:
          '<p>int a = 2, b = 3, c;</p><p>c = a + b;</p><p>printf(&quot;c = %d&quot;, c);</p>',
      },
    },
    {
      id: 'comparison',
      type: 'table',
      left: 100,
      top: 440,
      width: 700,
      height: 100,
      data: [[{ text: '复合语句' }, { text: '花括号后不加分号' }]],
    },
  ] as GeneratedSlideContent['elements'],
};
const speech = { type: 'text', content: '这里使用花括号把声明和执行语句组合在一起。' };
const cue = (elementId: string, name = 'spotlight') => ({
  type: 'action',
  name,
  params: { elementId },
});

describe('slide focus inventory for faithful PPT imports', () => {
  it('gives the model shape text, table cells and position instead of anonymous shape IDs', async () => {
    const call = vi.fn(async () => JSON.stringify([cue('compound-example'), speech]));
    await generateSceneActions(slideOutline(), content, call);
    const [system, user] = call.mock.calls[0] as unknown as [string, string];
    expect(user).toContain('int a = 2, b = 3, c;');
    expect(user).toContain('printf("c = %d", c);');
    expect(user).toContain('花括号后不加分号');
    expect(user).toContain('500');
    expect(system).toContain('decorative');
    expect(call).toHaveBeenCalledOnce();
  });

  it('never converts a nonexistent target into the first decorative object', async () => {
    const actions = await generateSceneActions(slideOutline(), content, async () =>
      JSON.stringify([cue('invented'), cue('missing', 'laser'), cue('missing', 'reveal'), speech]),
    );
    expect(actions.map((action) => action.type)).toEqual(['speech']);
    expect(actions[0]).toMatchObject({ text: speech.content });
  });

  it('keeps a valid exact binding even if the target is not the first element', async () => {
    const actions = await generateSceneActions(slideOutline(), content, async () =>
      JSON.stringify([cue('compound-example'), speech]),
    );
    expect(actions[0]).toMatchObject({ type: 'spotlight', elementId: 'compound-example' });
  });

  it('does not guess a focus for a fallback whole-page overview', async () => {
    const actions = await generateSceneActions(slideOutline(), content, async () => '[]');
    expect(actions.map((action) => action.type)).toEqual(['speech']);
  });
});
