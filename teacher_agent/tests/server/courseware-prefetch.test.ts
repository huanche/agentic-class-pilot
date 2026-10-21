import { describe, expect, it, vi } from 'vitest';
import { createCoursewarePrefetch } from '@/lib/server/courseware-prefetch';

describe('bounded courseware lookahead', () => {
  it('bounds both outstanding requests and retained lookahead', async () => {
    let active = 0,
      peak = 0;
    const release = new Map<number, () => void>();
    const load = vi.fn(async (index: number) => {
      active++;
      peak = Math.max(peak, active);
      await new Promise<void>((resolve) => release.set(index, resolve));
      active--;
      return index;
    });
    const queue = createCoursewarePrefetch(6, 2, load, new AbortController().signal);
    await vi.waitFor(() => expect(load).toHaveBeenCalledTimes(2));
    const first = queue.take(0);
    release.get(0)!();
    expect(await first).toBe(0);
    await vi.waitFor(() => expect(load).toHaveBeenCalledTimes(3));
    expect(peak).toBe(2);
    // A ready future result does not trigger an unbounded cascade.
    release.get(2)!();
    await Promise.resolve();
    expect(load).toHaveBeenCalledTimes(3);
    release.get(1)!();
    expect(await queue.take(1)).toBe(1);
    await vi.waitFor(() => expect(load).toHaveBeenCalledTimes(4));
    release.get(3)!();
    await queue.close();
  });
  it('aborts all speculative work and observes rejected promises', async () => {
    const aborted: number[] = [];
    const load = vi.fn(
      (index: number, signal: AbortSignal) =>
        new Promise<number>((_resolve, reject) => {
          signal.addEventListener(
            'abort',
            () => {
              aborted.push(index);
              reject(signal.reason);
            },
            { once: true },
          );
        }),
    );
    const queue = createCoursewarePrefetch(10, 2, load, new AbortController().signal);
    await vi.waitFor(() => expect(load).toHaveBeenCalledTimes(2));
    await queue.close();
    expect(aborted).toEqual([0, 1]);
    await expect(queue.take(0)).rejects.toThrow();
  });
  it('does not launch more requests after consuming a failed result', async () => {
    const load = vi.fn(async (index: number) => {
      if (index === 0) throw new Error('provider');
      return index;
    });
    const queue = createCoursewarePrefetch(6, 2, load, new AbortController().signal);
    await expect(queue.take(0)).rejects.toThrow('provider');
    expect(load).toHaveBeenCalledTimes(2);
    await queue.close();
  });
});
