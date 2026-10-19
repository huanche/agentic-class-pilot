import { promises as fs } from 'fs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { writeJsonFileAtomic } from '@/lib/server/classroom-storage';

vi.mock('@/lib/server/course-space-database', () => ({
  isCourseDatabaseConfigured: () => false,
  readClassroomFromDatabase: vi.fn(),
  upsertClassroomDatabaseRecord: vi.fn(),
}));

describe('atomic JSON writes with temporary file contention', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.spyOn(fs, 'mkdir').mockResolvedValue(undefined);
    vi.spyOn(fs, 'writeFile').mockResolvedValue(undefined);
  });
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it.each(['EPERM', 'EACCES', 'EBUSY'])(
    'retries temporary %s without deleting the original',
    async (code) => {
      const rename = vi
        .spyOn(fs, 'rename')
        .mockRejectedValueOnce(Object.assign(new Error('busy'), { code }))
        .mockResolvedValue(undefined);
      const remove = vi.spyOn(fs, 'unlink');
      const result = writeJsonFileAtomic('local/course.json', { status: 'ready' });
      await vi.runAllTimersAsync();
      await result;
      expect(rename).toHaveBeenCalledTimes(2);
      expect(rename.mock.calls[0]).toEqual(rename.mock.calls[1]);
      expect(fs.writeFile).toHaveBeenCalledTimes(1);
      expect(remove).not.toHaveBeenCalled();
    },
  );

  it('bounds retries and surfaces persistent failure', async () => {
    const error = Object.assign(new Error('locked'), { code: 'EPERM' });
    const rename = vi.spyOn(fs, 'rename').mockRejectedValue(error);
    const assertion = expect(writeJsonFileAtomic('local/course.json', {})).rejects.toBe(error);
    await vi.runAllTimersAsync();
    await assertion;
    expect(rename).toHaveBeenCalledTimes(7);
  });

  it('does not retry unrelated I/O failures', async () => {
    const error = Object.assign(new Error('no space'), { code: 'ENOSPC' });
    const rename = vi.spyOn(fs, 'rename').mockRejectedValue(error);
    await expect(writeJsonFileAtomic('local/course.json', {})).rejects.toBe(error);
    expect(rename).toHaveBeenCalledTimes(1);
  });
});
