import { readFileSync } from 'node:fs';
import { beforeEach, describe, expect, it, vi } from 'vitest';
const storage = vi.hoisted(() => ({
  readServerCourse: vi.fn(),
  readCourseMaterialBytes: vi.fn(),
  updateServerCourse: vi.fn(),
  saveMaterialExtraction: vi.fn(),
}));
vi.mock('@/lib/server/course-space-storage', () => storage);
import { parseStoredCourseMaterial } from '@/lib/server/course-material-parser';

describe('stored Word material retry', () => {
  beforeEach(() => vi.resetAllMocks());
  it('parses a failed DOC locally, saves the extraction and clears the cloud error', async () => {
    let course = {
      id: 'c1',
      teacherId: 't1',
      materials: [
        {
          id: 'm1',
          name: '教学进度.doc',
          mimeType: 'application/msword',
          sha256: 'source-hash',
          status: 'failed',
          error: 'MinerU Cloud API key is required',
        },
      ],
    };
    storage.readServerCourse.mockResolvedValue(course);
    storage.readCourseMaterialBytes.mockResolvedValue(
      readFileSync(new URL('../fixtures/word/legacy-text.doc', import.meta.url)),
    );
    storage.updateServerCourse.mockImplementation(async (_id, update) => {
      course = update(course);
      return course;
    });
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockRejectedValue(new Error('must not contact cloud'));
    try {
      const extraction = await parseStoredCourseMaterial({
        courseId: 'c1',
        materialId: 'm1',
        baseUrl: 'http://localhost:8088',
      });
      expect(extraction.text).toContain('This is a test of reviewing');
      expect(extraction.sourceSha256).toBe('source-hash');
      expect(extraction.parser).toBe('local-word');
      expect(storage.saveMaterialExtraction).toHaveBeenCalledWith(extraction);
      expect(course.materials[0].status).toBe('ready');
      expect(course.materials[0].error).toBeUndefined();
      expect(fetchSpy).not.toHaveBeenCalled();
    } finally {
      fetchSpy.mockRestore();
    }
  });
});
