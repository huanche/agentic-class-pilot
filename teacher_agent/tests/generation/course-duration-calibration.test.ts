import { describe, expect, it, vi } from 'vitest';
import type { Scene } from '@/lib/types/stage';
import { assessCourseDuration } from '@/lib/generation/course-duration';
import { calibrateCourseDuration } from '@/lib/generation/course-duration-calibration';

function page(id: string, target: number, actual?: number): Scene {
  return {
    id,
    stageId: 'stage',
    type: 'slide',
    title: id,
    order: Number(id),
    content: { type: 'slide', canvas: { elements: [] } },
    actions: [
      {
        id: `speech-${id}`,
        type: 'speech',
        text: '有效教学内容'.repeat(20),
        audioId: `audio-${id}`,
      },
    ],
    timing: { plannedDurationSec: target, measuredDurationSec: actual },
  } as unknown as Scene;
}

describe('whole-course measured calibration', () => {
  it('reduces accumulated overflow by correcting the page with the largest excess', async () => {
    const original = [page('1', 60, 80), page('2', 540, 570), page('3', 600, 622.8)];
    const accepted = vi.fn();
    const regenerate = vi.fn(async (scene: Scene) => page(scene.id, 540, 540));
    const result = await calibrateCourseDuration(original, 20, 3, {
      regenerate,
      dispose: vi.fn(),
      onAccepted: accepted,
    });
    expect(regenerate).toHaveBeenCalledOnce();
    expect(regenerate.mock.calls[0][0].id).toBe('2');
    expect(assessCourseDuration(result.scenes, 20, 3).status).toBe('within-tolerance');
    expect(original[1].timing?.measuredDurationSec).toBe(570);
    expect(accepted).toHaveBeenCalledOnce();
  });

  it('adds useful narration to the largest deficit when the course is short', async () => {
    const original = [page('1', 300, 250), page('2', 400, 370), page('3', 500, 480)];
    const regenerate = vi.fn(async (scene: Scene) => page(scene.id, 300, 300));
    const result = await calibrateCourseDuration(original, 20, 3, { regenerate, dispose: vi.fn() });
    expect(regenerate.mock.calls[0][0].id).toBe('1');
    expect(assessCourseDuration(result.scenes, 20, 3).actualSeconds).toBe(1150);
    expect(result.attempts).toBe(1);
  });

  it('does not spend more calls when opposite page errors already balance', async () => {
    const regenerate = vi.fn();
    await calibrateCourseDuration([page('1', 60, 90), page('2', 1140, 1110)], 20, 2, {
      regenerate,
      dispose: vi.fn(),
    });
    expect(regenerate).not.toHaveBeenCalled();
  });

  it('does not estimate missing audio or an incomplete course', async () => {
    const regenerate = vi.fn();
    for (const [pages, expected] of [
      [[page('1', 60)], 1],
      [[page('1', 60, 20)], 2],
    ] as const) {
      await calibrateCourseDuration([...pages], 1, expected, { regenerate, dispose: vi.fn() });
    }
    expect(regenerate).not.toHaveBeenCalled();
  });

  it('bounds additional paid calls and disposes only rejected new candidates', async () => {
    const original = [page('1', 60, 90)];
    const dispose = vi.fn();
    const regenerate = vi.fn(async () => page('1', 60, 120));
    const result = await calibrateCourseDuration(original, 1, 1, { regenerate, dispose });
    expect(regenerate).toHaveBeenCalledTimes(2);
    expect(dispose).toHaveBeenCalledTimes(2);
    expect(result.scenes).toBe(original);
    expect(dispose.mock.calls.some(([value]) => value === original[0])).toBe(false);
  });

  it('protects excluded active/edited pages and retains drafts on provider failure', async () => {
    const original = [page('1', 60, 90), page('2', 60, 80)];
    const regenerate = vi.fn(async (_scene: Scene) => {
      throw new Error('provider unavailable');
    });
    const result = await calibrateCourseDuration(
      original,
      2,
      2,
      { regenerate, dispose: vi.fn() },
      { excludedSceneIds: new Set(['1']) },
    );
    expect(regenerate.mock.calls[0][0].id).toBe('2');
    expect(result.scenes).toBe(original);
  });

  it('preserves the original on unknown candidate duration and propagates cancellation', async () => {
    const original = [page('1', 60, 90)];
    const dispose = vi.fn();
    const result = await calibrateCourseDuration(
      original,
      1,
      1,
      {
        regenerate: async () => page('1', 60),
        dispose,
      },
      { maxAttempts: 1 },
    );
    expect(result.scenes).toBe(original);
    expect(result.attempts).toBe(1);
    expect(dispose).toHaveBeenCalledOnce();
    const abort = new DOMException('aborted', 'AbortError');
    await expect(
      calibrateCourseDuration(original, 1, 1, {
        regenerate: async () => {
          throw abort;
        },
        dispose,
      }),
    ).rejects.toBe(abort);
  });

  it('does not replace a page when acceptance detects concurrent editing', async () => {
    const original = [page('1', 60, 90)];
    const candidate = page('1', 60, 60);
    const dispose = vi.fn();
    await expect(
      calibrateCourseDuration(original, 1, 1, {
        regenerate: async () => candidate,
        dispose,
        onAccepted: () => {
          throw new DOMException('edited', 'AbortError');
        },
      }),
    ).rejects.toMatchObject({ name: 'AbortError' });
    expect(dispose).toHaveBeenCalledWith(candidate);
    expect(original[0].timing?.measuredDurationSec).toBe(90);
  });
});
