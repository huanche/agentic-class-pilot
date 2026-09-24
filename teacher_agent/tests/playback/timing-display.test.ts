import { describe, expect, it } from 'vitest';
import {
  formatPlaybackDuration,
  getOutlineDurationSeconds,
  inferTargetDurationMinutes,
} from '@/lib/playback/timing-display';
import type { SceneOutline } from '@/lib/types/generation';

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

  it('uses one minute per quiz question', () => {
    expect(
      getOutlineDurationSeconds(
        outline({
          type: 'quiz',
          quizConfig: { questionCount: 3, difficulty: 'easy', questionTypes: ['single'] },
        }),
        45,
        10,
      ),
    ).toBe(180);
  });
});
