import { beforeEach, describe, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({ read: vi.fn(), update: vi.fn(), generate: vi.fn() }));
vi.mock('@/lib/server/course-space-storage', () => ({
  readServerCourse: mocks.read,
  updateServerCourse: mocks.update,
}));
vi.mock('@/lib/server/teacher-course-operations', () => ({
  generateLessonFileContent: mocks.generate,
}));
import { ensureLessonReviewFiles } from '@/lib/server/lesson-review-files';
const makeCourse = () => ({
  id: 'c',
  materials: [{ id: 'a' }, { id: 'b' }],
  modules: [
    {
      id: 'm',
      lessons: [
        {
          id: 'l',
          title: '第1周',
          materialIds: ['b'],
          files: [
            { id: 'edited', type: 'lesson-objectives', content: '教师修订目标', status: 'ready' },
          ],
        },
      ],
    },
  ],
});
describe('lesson review documents', () => {
  beforeEach(() => vi.resetAllMocks());
  it('uses lesson materials and preserves teacher revisions while adding knowledge points', async () => {
    const course = makeCourse();
    mocks.read.mockResolvedValue(course);
    mocks.generate.mockResolvedValue({ 'knowledge-points': '本次知识点' });
    await ensureLessonReviewFiles('c', 'l');
    expect(mocks.generate.mock.calls[0][0].materials).toEqual([{ id: 'b' }]);
    expect(mocks.generate.mock.calls[0][2]).toEqual(['knowledge-points']);
    const updated = mocks.update.mock.calls[0][1](course);
    expect(updated.modules[0].lessons[0].files[0]).toEqual(course.modules[0].lessons[0].files[0]);
    expect(updated.modules[0].lessons[0].files[1]).toMatchObject({
      type: 'knowledge-points',
      status: 'draft',
      content: '本次知识点',
    });
  });
  it('does not overwrite existing documents on retries', async () => {
    const course = makeCourse();
    course.modules[0].lessons[0].files.push({
      id: 'k',
      type: 'knowledge-points',
      content: '已修改',
      status: 'ready',
    });
    mocks.read.mockResolvedValue(course);
    await ensureLessonReviewFiles('c', 'l');
    expect(mocks.generate).not.toHaveBeenCalled();
    expect(mocks.update).not.toHaveBeenCalled();
  });
  it('rejects incomplete output without saving partial documents', async () => {
    mocks.read.mockResolvedValue(makeCourse());
    mocks.generate.mockResolvedValue({});
    await expect(ensureLessonReviewFiles('c', 'l')).rejects.toThrow('生成不完整');
    expect(mocks.update).not.toHaveBeenCalled();
  });
});
