import { afterEach, describe, expect, it, vi } from 'vitest';
import { createCoursewarePerformance } from '@/lib/server/courseware-performance';
afterEach(() => vi.restoreAllMocks());
describe('courseware phase timings', () => {
  it('records live elapsed time and keeps overlapping work distinct from wall time', async () => {
    let now = 100;
    vi.spyOn(performance, 'now').mockImplementation(() => now);
    const stats = createCoursewarePerformance(true, 2);
    let done!: () => void;
    const barrier = new Promise<void>((resolve) => {
      done = resolve;
    });
    const content = stats.measure('content', () => barrier, 2);
    const audio = stats.measure('audio', () => barrier, 1);
    now = 350;
    expect(stats.snapshot()).toMatchObject({
      elapsedMs: 250,
      timings: [
        { phase: 'content', durationMs: 250, status: 'running' },
        { phase: 'audio', durationMs: 250, status: 'running' },
      ],
    });
    done();
    await Promise.all([content, audio]);
    stats.pageReady();
    const final = stats.snapshot(true);
    expect(final.elapsedMs).toBe(250);
    expect(final.timings.reduce((total, timing) => total + timing.durationMs, 0)).toBe(500);
    expect(final.firstPageReadyMs).toBe(250);
    expect(final.timings.every((timing) => timing.status === 'ok')).toBe(true);
  });
  it('retains failed attempt time and cache counters without recording inputs', async () => {
    const stats = createCoursewarePerformance(true, 2);
    await expect(
      stats.measure(
        'actions',
        async () => {
          throw new Error('private input');
        },
        1,
        2,
      ),
    ).rejects.toThrow();
    stats.cache('hit');
    stats.cache('miss');
    stats.cache('shared');
    stats.cache('bypass');
    const final = stats.snapshot(true);
    expect(final).toMatchObject({
      audioCache: { hits: 1, misses: 1, shared: 1, bypassed: 1 },
      timings: [{ phase: 'actions', pageOrder: 1, attempt: 2, status: 'error' }],
    });
    expect(JSON.stringify(final)).not.toContain('private input');
  });
});
