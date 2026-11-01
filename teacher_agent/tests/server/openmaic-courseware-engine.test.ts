import { describe, expect, it, vi } from 'vitest';
import { buildCompleteScene, generateSceneActions } from '@openmaic/generation';
import {
  generateOpenmaicCourseware,
  type OpenmaicCheckpoint,
  type OpenmaicEngineServices,
} from '@/lib/server/openmaic-courseware-engine';
import type { Scene } from '@/lib/types/stage';
import type { SceneOutline } from '@/lib/types/generation';

const outlines = [1, 2, 3, 4, 5].map(
  (order) =>
    ({
      id: `o${order}`,
      order,
      type: 'slide',
      title: `Page ${order}`,
      description: '',
      keyPoints: [],
    }) as SceneOutline,
);
const page = (order: number) =>
  ({
    id: `s${order}`,
    order,
    type: 'slide',
    actions: [{ id: `a${order}`, type: 'speech', text: `Speech ${order}` }],
  }) as Scene;
function setup() {
  const checkpoints = new Map<number, OpenmaicCheckpoint<string>>();
  const saved: Scene[] = [];
  const events: string[] = [];
  const controller = new AbortController();
  const services: OpenmaicEngineServices<string> = {
    content: vi.fn(async (outline) => {
      events.push(`content${outline.order}`);
      return `${outline.order}`;
    }),
    actions: vi.fn(async (outline) => page(outline.order)),
    narrate: vi.fn(async () => {}),
    read: async (order) => structuredClone(checkpoints.get(order) ?? {}),
    checkpoint: async (order, value) => {
      checkpoints.set(order, structuredClone(value));
    },
    save: vi.fn(async (scene) => {
      events.push(`saved${scene.order}`);
      saved.push(structuredClone(scene));
    }),
    discard: vi.fn(async () => {}),
    phase: vi.fn(async () => {}),
  };
  const run = () =>
    generateOpenmaicCourseware({
      outlines,
      completed: saved,
      concurrency: 2,
      signal: controller.signal,
      services,
    });
  return { checkpoints, saved, events, services, controller, run };
}
describe('OpenMAIC server generation ordering', () => {
  it('prioritizes the first complete page, then prefetches content with ordered speech context', async () => {
    const s = setup();
    await s.run();
    expect(s.events.indexOf('saved1')).toBeLessThan(s.events.indexOf('content2'));
    expect(s.saved.map((scene) => scene.order)).toEqual([1, 2, 3, 4, 5]);
    expect(vi.mocked(s.services.actions).mock.calls[1][2]?.actions?.[0]).toMatchObject({
      text: 'Speech 1',
    });
    expect(s.services.actions).toHaveBeenCalledTimes(5);
    expect(s.services.narrate).toHaveBeenCalledTimes(5); // No duration-driven rewrites.
  });
  it('retries failed narration from its actions checkpoint without paying for the models again', async () => {
    const s = setup();
    vi.mocked(s.services.narrate).mockImplementationOnce(async () => {
      throw new Error('voice unavailable');
    });
    await expect(s.run()).rejects.toThrow('voice unavailable');
    expect(s.checkpoints.get(1)?.scene?.id).toBe('s1');
    expect(s.services.discard).toHaveBeenCalledOnce();
    await s.run();
    expect(
      vi.mocked(s.services.actions).mock.calls.filter(([outline]) => outline.order === 1),
    ).toHaveLength(1);
    expect(
      vi.mocked(s.services.content).mock.calls.filter(([outline]) => outline.order === 1),
    ).toHaveLength(1);
    expect(s.saved).toHaveLength(5);
  });
  it('does not save or start more pages after cancellation during narration', async () => {
    const s = setup();
    vi.mocked(s.services.narrate).mockImplementationOnce(async () => {
      s.controller.abort();
    });
    await expect(s.run()).rejects.toThrow();
    expect(s.services.save).not.toHaveBeenCalled();
    expect(s.services.discard).toHaveBeenCalledOnce();
    expect(s.services.content).toHaveBeenCalledOnce();
  });
  it('skips existing complete pages on retry', async () => {
    const s = setup();
    s.saved.push(page(1), page(2));
    await s.run();
    expect(vi.mocked(s.services.content).mock.calls.map(([outline]) => outline.order)).toEqual([
      3, 4, 5,
    ]);
    expect(vi.mocked(s.services.actions).mock.calls[0][2]?.id).toBe('s2');
  });
  it('repairs only the current page actions while continuing the original five-page plan', async () => {
    const s = setup();
    s.saved.push(page(1), page(2));
    s.saved[0].actions![0] = {
      id: 'a1',
      type: 'speech',
      text: 'Speech 1',
      audioId: 'original-audio',
    };
    const preserved = structuredClone(s.saved);
    const attempts = new Map<number, number>();
    vi.mocked(s.services.actions).mockImplementation(async (outline) => {
      const content = { elements: [] };
      const actions = await generateSceneActions(outline, content, async () => {
        const attempt = (attempts.get(outline.order) ?? 0) + 1;
        attempts.set(outline.order, attempt);
        return JSON.stringify(
          outline.order === 3 && attempt === 1
            ? [{ type: 'action', name: 'unknown_action', params: {} }]
            : [{ type: 'action', name: 'text', params: { content: `Speech ${outline.order}` } }],
        );
      });
      return buildCompleteScene(outline, content, actions, 'stage')! as Scene;
    });
    await s.run();
    expect(s.saved.map((scene) => scene.order)).toEqual([1, 2, 3, 4, 5]);
    expect(s.saved.slice(0, 2)).toEqual(preserved);
    expect([...attempts.entries()]).toEqual([
      [3, 2],
      [4, 1],
      [5, 1],
    ]);
    expect(vi.mocked(s.services.content).mock.calls.map(([outline]) => outline.order)).toEqual([
      3, 4, 5,
    ]);
    expect(vi.mocked(s.services.narrate).mock.calls.map(([scene]) => scene.order)).toEqual([
      3, 4, 5,
    ]);
  });
});
