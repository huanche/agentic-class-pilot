import { describe, expect, it } from 'vitest';
import {
  isAutoPlayedStudentScene,
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
  it('auto-plays narrated slides and scripted demos, but waits for quiz answers', () => {
    expect(isAutoPlayedStudentScene(scenes[0])).toBe(true);
    expect(isAutoPlayedStudentScene(scenes[2])).toBe(true);
    expect(isAutoPlayedStudentScene(scenes[1])).toBe(false);
    expect(isAutoPlayedStudentScene(scenes[4])).toBe(false);
  });

  it('advances through activity scenes in lesson order', () => {
    expect(nextStudentPlaybackSlide(scenes, 'slide-1')?.id).toBe('quiz-1');
    expect(nextStudentPlaybackSlide(scenes, 'quiz-1')?.id).toBe('interactive-1');
    expect(nextStudentPlaybackSlide(scenes, 'interactive-1')?.id).toBe('slide-2');
  });

  it('includes the final activity', () => {
    expect(nextStudentPlaybackSlide(scenes, 'slide-2')?.id).toBe('pbl-1');
    expect(nextStudentPlaybackSlide(scenes, 'pbl-1')).toBeUndefined();
  });

  it('ends only after the final scene', () => {
    expect(isFinalStudentPlaybackSlide(scenes, 'slide-1')).toBe(false);
    expect(isFinalStudentPlaybackSlide(scenes, 'slide-2')).toBe(false);
    expect(isFinalStudentPlaybackSlide(scenes, 'pbl-1')).toBe(true);
  });
});
