import { describe, expect, it } from 'vitest';
import { renderQuizContent } from '@/lib/quiz/content';
import { studentPlaybackStorageId } from '@/lib/playback/student-storage';

describe('student exercise readability', () => {
  it('preserves code newlines, indentation and dollar signs verbatim', () => {
    const code = 'int main() {\n  printf("$5\\n");\n  return 0;\n}\n';
    const segments = renderQuizContent('调试以下程序：\n```c\n' + code + '```\n解释 `a < b`。');
    expect(segments.filter((part) => part.type === 'code')).toEqual([
      { type: 'code', value: code, block: true },
      { type: 'code', value: 'a < b', block: false },
    ]);
  });
  it('isolates resume state by host learner key and stage', () => {
    expect(studentPlaybackStorageId('course', '?resumeKey=12345678-12345678')).toBe(
      'student:12345678-12345678:course',
    );
    expect(studentPlaybackStorageId('course', '?resumeKey=bad/key')).toBe('course');
  });
});
