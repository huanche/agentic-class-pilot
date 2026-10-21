/** Timings contain identifiers/counts only, never prompts, text, or provider credentials. */
export interface CoursewareTiming {
  phase: string;
  pageOrder?: number;
  attempt?: number;
  startMs?: number;
  durationMs: number;
  status: 'running' | 'ok' | 'error' | 'cancelled';
}

export interface CoursewarePerformance {
  engine?: 'openmaic';
  version: 1;
  startedAt: number;
  elapsedMs: number;
  finishedAt?: number;
  firstPageReadyMs?: number;
  pipeline: boolean;
  prefetch: number;
  timings: CoursewareTiming[];
  audioCache: { hits: number; misses: number; shared: number; bypassed: number };
}
