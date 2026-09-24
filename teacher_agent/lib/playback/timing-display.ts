import type { Scene, Stage } from '@/lib/types/stage';
import type { SceneOutline } from '@/lib/types/generation';

export const DEFAULT_COURSE_MINUTES = 45;
export const QUIZ_SECONDS_PER_QUESTION = 60;

export function formatPlaybackDuration(totalSeconds: number): string {
  const safe = Math.max(0, Math.round(totalSeconds));
  const hours = Math.floor(safe / 3600);
  const minutes = Math.floor((safe % 3600) / 60);
  const seconds = safe % 60;
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
    : `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}

export function inferTargetDurationMinutes(requirement: string, pageCount = 0): number {
  const match = requirement.match(/(\d+(?:\.\d+)?)\s*(?:分钟|min(?:ute)?s?)/i);
  if (match) return Math.max(1, Math.round(Number(match[1])));
  return pageCount > 0 ? Math.max(1, Math.round(pageCount * 1.5)) : DEFAULT_COURSE_MINUTES;
}

export function getOutlineDurationSeconds(
  outline: SceneOutline,
  targetDurationMinutes: number,
  outlineCount: number,
): number {
  if (outline.type === 'quiz') {
    return Math.max(1, outline.quizConfig?.questionCount ?? 3) * QUIZ_SECONDS_PER_QUESTION;
  }
  return Math.max(
    5,
    Math.round(
      outline.estimatedDuration ?? (targetDurationMinutes * 60) / Math.max(1, outlineCount),
    ),
  );
}

export function getSceneDurationSeconds(
  scene: Scene,
  stage: Stage | null,
  scenes: Scene[],
): number {
  if (scene.type === 'quiz') {
    return scene.content.questions.length * QUIZ_SECONDS_PER_QUESTION;
  }
  if (scene.timing?.plannedDurationSec != null) return scene.timing.plannedDurationSec;

  const courseTargetSeconds = (stage?.timing?.targetDurationMinutes ?? DEFAULT_COURSE_MINUTES) * 60;
  const reservedSeconds = scenes.reduce((sum, candidate) => {
    if (candidate.id === scene.id) return sum;
    if (candidate.type === 'quiz') {
      return sum + candidate.content.questions.length * QUIZ_SECONDS_PER_QUESTION;
    }
    return sum + (candidate.timing?.plannedDurationSec ?? 0);
  }, 0);
  const unplannedCount = Math.max(
    1,
    scenes.filter(
      (candidate) => candidate.type !== 'quiz' && candidate.timing?.plannedDurationSec == null,
    ).length,
  );
  return Math.max(5, Math.floor((courseTargetSeconds - reservedSeconds) / unplannedCount));
}

export function getCourseDurationSeconds(stage: Stage | null, scenes: Scene[]): number {
  if (stage?.timing?.targetDurationMinutes != null) {
    return stage.timing.targetDurationMinutes * 60;
  }
  return scenes.reduce((sum, scene) => sum + getSceneDurationSeconds(scene, stage, scenes), 0);
}
