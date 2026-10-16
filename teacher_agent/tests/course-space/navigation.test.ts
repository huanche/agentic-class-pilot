import { describe, expect, it } from 'vitest';
import {
  courseWorkspaceUrl,
  teacherReturnUrl,
  withTeacherReturn,
} from '@/lib/course-space/navigation';

describe('teacher return destinations', () => {
  it('uses a stable workspace parent on direct entry and review round trips', () => {
    const parent = courseWorkspaceUrl('course-a');
    expect(teacherReturnUrl(null, parent)).toBe(parent);
    expect(teacherReturnUrl('/course-space/course-a/review/a', parent)).toBe(parent);
    expect(teacherReturnUrl('/course-space/course-a/artifacts/a/view', parent)).toBe(parent);
    expect(teacherReturnUrl('/classes/course-a', parent)).toBe('/classes/course-a');
  });
  it.each([
    '//evil.test',
    '/\\evil.test',
    '/login',
    'https://evil.test',
    '/course-space/../../login',
  ])('rejects unrelated or external destinations: %s', (from) => {
    expect(teacherReturnUrl(from)).toBe('/course-space');
  });
  it('preserves existing player query parameters while attaching a return destination', () => {
    const target = new URL(
      withTeacherReturn('/classroom/a?replay=1', courseWorkspaceUrl('course-a')),
      'https://teacher.invalid',
    );
    expect(target.searchParams.get('replay')).toBe('1');
    expect(target.searchParams.get('from')).toBe('/course-space?workspace=course-a');
  });
});
