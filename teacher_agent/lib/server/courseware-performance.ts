import type {
  CoursewarePerformance,
  CoursewareTiming,
} from '@/lib/generation/courseware-performance';

export function createCoursewarePerformance(pipeline: boolean, prefetch: number) {
  const started = performance.now();
  const active = new Map<CoursewareTiming, number>();
  const value: CoursewarePerformance = {
    version: 1,
    startedAt: Date.now(),
    elapsedMs: 0,
    pipeline,
    prefetch,
    timings: [],
    audioCache: { hits: 0, misses: 0, shared: 0, bypassed: 0 },
  };
  return {
    detail(phase: string, durationMs: number, pageOrder?: number) {
      if (!Number.isFinite(durationMs) || durationMs < 0) return;
      value.timings.push({
        phase,
        pageOrder,
        durationMs: Math.round(durationMs),
        status: 'ok',
      });
    },
    async measure<T>(
      phase: string,
      work: () => Promise<T>,
      pageOrder?: number,
      attempt?: number,
    ): Promise<T> {
      const start = performance.now();
      const timing: CoursewareTiming = {
        phase,
        pageOrder,
        attempt,
        startMs: Math.round(start - started),
        durationMs: 0,
        status: 'running',
      };
      value.timings.push(timing);
      active.set(timing, start);
      let status: 'ok' | 'error' | 'cancelled' = 'ok';
      try {
        return await work();
      } catch (error) {
        status = error instanceof Error && error.name === 'AbortError' ? 'cancelled' : 'error';
        throw error;
      } finally {
        timing.durationMs = Math.round(performance.now() - start);
        timing.status = status;
        active.delete(timing);
      }
    },
    cache(status: 'hit' | 'miss' | 'shared' | 'bypass') {
      value.audioCache[
        status === 'hit'
          ? 'hits'
          : status === 'miss'
            ? 'misses'
            : status === 'shared'
              ? 'shared'
              : 'bypassed'
      ]++;
    },
    pageReady() {
      value.firstPageReadyMs ??= Math.round(performance.now() - started);
    },
    snapshot(finished = false): CoursewarePerformance {
      for (const [timing, start] of active)
        timing.durationMs = Math.round(performance.now() - start);
      value.elapsedMs = Math.round(performance.now() - started);
      if (finished) value.finishedAt = Date.now();
      return structuredClone(value);
    },
  };
}
