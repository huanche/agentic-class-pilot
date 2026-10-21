export type Outcome<T> = { ok: true; value: T } | { ok: false; error: unknown };
export const settle = <T>(promise: Promise<T>): Promise<Outcome<T>> =>
  promise.then(
    (value) => ({ ok: true, value }),
    (error) => ({ ok: false, error }),
  );
export function unwrap<T>(outcome: Outcome<T>): T {
  if (!outcome.ok) throw outcome.error;
  return outcome.value;
}

/** Sliding lookahead: bounded in-flight work AND retained results; errors are observed. */
export function createCoursewarePrefetch<T>(
  count: number,
  window: number,
  load: (index: number, signal: AbortSignal) => Promise<T>,
  signal: AbortSignal,
  eager = true,
) {
  const abort = new AbortController();
  const combined = AbortSignal.any([signal, abort.signal]);
  const pending = new Map<number, Promise<Outcome<T>>>();
  let next = 0;
  let consumed = 0;
  const fill = () => {
    while (!combined.aborted && next < count && next < consumed + window) {
      const index = next++;
      pending.set(
        index,
        settle(
          Promise.resolve().then(() => {
            combined.throwIfAborted();
            return load(index, combined);
          }),
        ),
      );
    }
  };
  if (eager) fill();
  return {
    async take(index: number): Promise<T> {
      combined.throwIfAborted();
      if (!eager) pending.set(index, settle(load(index, combined)));
      const work = pending.get(index);
      if (!work) throw new Error('Invalid prefetch order');
      const result = await work;
      pending.delete(index);
      consumed = index + 1;
      if (eager && result.ok) fill();
      return unwrap(result);
    },
    async close() {
      abort.abort();
      await Promise.all(pending.values());
      pending.clear();
    },
  };
}
