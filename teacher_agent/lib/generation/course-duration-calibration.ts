import type { Scene } from '@/lib/types/stage';
import {
  assessCourseDuration,
  measuredSceneSeconds,
  narrationDurationFeedback,
  type DurationFeedback,
} from './course-duration';

export const MAX_COURSE_DURATION_CORRECTIONS = 2;

export interface CourseCalibrationCallbacks {
  regenerate: (scene: Scene, feedback: DurationFeedback) => Promise<Scene>;
  dispose: (scene: Scene) => Promise<void>;
  onAttempt?: (attempt: number) => void | Promise<void>;
  onAccepted?: (previous: Scene, candidate: Scene) => void | Promise<void>;
}

export async function calibrateCourseDuration(
  scenes: Scene[],
  minutes: number,
  expectedPages: number,
  callbacks: CourseCalibrationCallbacks,
  options: { maxAttempts?: number; excludedSceneIds?: ReadonlySet<string> } = {},
): Promise<{ scenes: Scene[]; attempts: number }> {
  let selected = scenes;
  let attempts = 0;
  const dispose = async (page: Scene) => {
    try {
      await callbacks.dispose(page);
    } catch {
      /* Preserve the usable course even if transient cleanup fails. */
    }
  };
  const maximum = Math.min(
    MAX_COURSE_DURATION_CORRECTIONS,
    Math.max(0, options.maxAttempts ?? MAX_COURSE_DURATION_CORRECTIONS),
  );
  while (attempts < maximum) {
    const report = assessCourseDuration(selected, minutes, expectedPages);
    if (report.actualSeconds == null || report.status === 'within-tolerance') break;
    const direction = report.actualSeconds > report.targetSeconds ? 1 : -1;
    const page = selected
      .filter(
        (value) =>
          (value.type === 'slide' || value.type === 'interactive') &&
          !options.excludedSceneIds?.has(value.id) &&
          (value.timing?.plannedDurationSec ?? 0) > 0,
      )
      .map((value) => ({
        value,
        error: ((measuredSceneSeconds(value) ?? 0) - value.timing!.plannedDurationSec!) * direction,
      }))
      .filter((value) => value.error > 0)
      .sort((a, b) => b.error - a.error || a.value.order - b.value.order)[0]?.value;
    if (!page) break;
    attempts++;
    let candidate: Scene | undefined;
    try {
      await callbacks.onAttempt?.(attempts);
      candidate = await callbacks.regenerate(page, {
        ...narrationDurationFeedback(page, page.timing!.plannedDurationSec!),
        courseMeasuredSeconds: report.actualSeconds,
        courseTargetSeconds: report.targetSeconds,
      });
      if (
        candidate.id !== page.id ||
        candidate.stageId !== page.stageId ||
        candidate.type !== page.type ||
        candidate.order !== page.order ||
        candidate.timing?.plannedDurationSec !== page.timing?.plannedDurationSec
      ) {
        await dispose(candidate);
        candidate = undefined;
        continue;
      }
      const next = selected.map((value) => (value.id === page.id ? candidate! : value));
      const nextReport = assessCourseDuration(next, minutes, expectedPages);
      if (
        nextReport.actualSeconds != null &&
        Math.abs(nextReport.actualSeconds - report.targetSeconds) <
          Math.abs(report.actualSeconds - report.targetSeconds)
      ) {
        await callbacks.onAccepted?.(page, candidate);
        selected = next;
      } else {
        await dispose(candidate);
      }
      candidate = undefined;
    } catch (error) {
      if (candidate) await dispose(candidate);
      if (error instanceof Error && error.name === 'AbortError') throw error;
      break; // Keep the last usable course on provider or persistence failure.
    }
  }
  return { scenes: selected, attempts };
}
