// @vitest-environment jsdom

import { beforeEach, describe, expect, it } from 'vitest';
import { BrowserCourseSpaceRepository, DEFAULT_TEACHER_ID } from '@/lib/course-space';

describe('BrowserCourseSpaceRepository', () => {
  beforeEach(() => localStorage.clear());

  it('isolates courses by teacher while keeping tenant-ready identifiers', async () => {
    const repository = new BrowserCourseSpaceRepository();
    const mine = await repository.create({ teacherId: DEFAULT_TEACHER_ID, title: '无线通信基础' });
    await repository.create({ teacherId: 'another-teacher', title: '其他课程' });

    expect(await repository.listByTeacher(DEFAULT_TEACHER_ID)).toEqual([mine]);
    expect(mine.modules).toEqual([]);
    expect(mine.materials).toEqual([]);
  });
});
