import { describe, expect, it } from 'vitest';
import {
  isFinalStudentPlaybackSlide,
  nextStudentPlaybackSlide,
} from '@/lib/playback/student-player-playlist';

const scenes = [
  { id: 'slide-1', type: 'slide' as const },
  { id: 'quiz-1', type: 'quiz' as const },
  { id: 'interactive-1', type: 'interactive' as const },
  { id: 'slide-2', type: 'slide' as const },
  { id: 'pbl-1', type: 'pbl' as const },
];

describe('student player playlist', () => {
  it('advances to the next slide while skipping activity scenes', () => {
    expect(nextStudentPlaybackSlide(scenes, 'slide-1')?.id).toBe('slide-2');
  });

  it('does not expose an activity scene as the next video page', () => {
    expect(nextStudentPlaybackSlide(scenes, 'quiz-1')?.id).toBe('slide-2');
  });

  it('ends after the final slide even when activities follow it', () => {
    expect(isFinalStudentPlaybackSlide(scenes, 'slide-1')).toBe(false);
    expect(isFinalStudentPlaybackSlide(scenes, 'slide-2')).toBe(true);
  });
});
