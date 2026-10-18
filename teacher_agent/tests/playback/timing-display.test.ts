import { describe, expect, it } from 'vitest';
import {
  formatPlaybackDuration,
  getOutlineDurationSeconds,
  inferTargetDurationMinutes,
  getSceneDurationSeconds,
} from '@/lib/playback/timing-display';
import type { SceneOutline } from '@/lib/types/generation';
import type { Scene, Stage } from '@/lib/types/stage';

const outline = (updates: Partial<SceneOutline> = {}): SceneOutline => ({
  id: 'outline-1',
  type: 'slide',
  title: 'Page',
  description: 'Description',
  keyPoints: [],
  order: 1,
  ...updates,
});

describe('playback timing display', () => {
  it('formats page and long course durations', () => {
    expect(formatPlaybackDuration(90)).toBe('01:30');
    expect(formatPlaybackDuration(3723)).toBe('1:02:03');
  });

  it('reads a requested course duration from natural language', () => {
    expect(inferTargetDurationMinutes('生成一套42分钟的交换原理课程', 12)).toBe(42);
    expect(inferTargetDurationMinutes('Build a 30 minute lesson', 12)).toBe(30);
  });

  it('reserves five minutes per quiz question', () => {
    expect(
      getOutlineDurationSeconds(
        outline({
          type: 'quiz',
          quizConfig: { questionCount: 3, difficulty: 'easy', questionTypes: ['single'] },
        }),
        45,
        10,
      ),
    ).toBe(900);
  });

  it('uses five minutes per question even when an old quiz stores a shorter measured duration', () => {
    const quiz = {
      id: 'quiz',
      type: 'quiz',
      content: { type: 'quiz', questions: [{ id: 'one' }, { id: 'two' }] },
      actions: [],
      timing: { plannedDurationSec: 120, measuredDurationSec: 120 },
    } as unknown as Scene;
    expect(getSceneDurationSeconds(quiz, { timing: { budgetVersion: 1 } } as Stage, [quiz])).toBe(
      600,
    );
    expect(
      getOutlineDurationSeconds(
        outline({
          type: 'quiz',
          quizConfig: { questionCount: 2, difficulty: 'easy', questionTypes: ['single'] },
          durationBudget: { targetSeconds: 120 },
        }),
        28,
        5,
      ),
    ).toBe(600);
  });
});
