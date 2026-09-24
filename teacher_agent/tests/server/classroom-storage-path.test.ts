import path from 'path';
import { describe, expect, it } from 'vitest';

import { CLASSROOMS_DIR, resolveClassroomFilePath } from '@/lib/server/classroom-storage';

describe('resolveClassroomFilePath', () => {
  it('rejects traversal and absolute-style ids', () => {
    expect(() => resolveClassroomFilePath('../../../../tmp/openmaic-escape')).toThrow(
      /outside the classrooms directory/,
    );
    expect(() => resolveClassroomFilePath('/tmp/openmaic-escape')).toThrow(
      /outside the classrooms directory/,
    );
  });

  it('keeps ordinary ids inside CLASSROOMS_DIR', () => {
    expect(resolveClassroomFilePath('abc-123_XY')).toBe(
      path.join(path.resolve(CLASSROOMS_DIR), 'abc-123_XY.json'),
    );
  });
});
