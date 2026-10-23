import { expect, it, vi } from 'vitest';
import type { CourseSpace, CourseMaterialExtraction } from '@/lib/course-space';
import { createCoursewareGenerationSession } from '@/lib/course-space/courseware-generation';

const course: CourseSpace = {
  id: 'test',
  title: '测试课程',
  teacherId: 'teacher',
  status: 'draft',
  modules: [],
  createdAt: 1,
  updatedAt: 1,
  materials: [
    {
      id: 'ppt',
      name: '循环.pptx',
      status: 'ready',
      teacherId: 'teacher',
      courseId: 'test',
      mimeType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
      size: 100,
      storageKey: 'ppt',
      createdAt: 1,
      updatedAt: 1,
    },
  ],
};
const options = {
  course,
  scope: { type: 'course' as const },
  sessionId: 'test',
  materialIds: ['ppt'],
  targetDurationMinutes: '28',
  instruction: '解释边界条件',
};

it.each(['faithful', 'learning-skills-enhanced'] as const)(
  'both workspace modes %s read the original PPTX rather than stale empty extraction',
  async (conversionMode) => {
    const read = vi
      .fn<() => Promise<CourseMaterialExtraction>>()
      .mockRejectedValue(new Error('stale text'));
    const prepare = vi.fn(async (_material, session) => ({
      ...session,
      previewPhase: 'ppt-review' as const,
      pptxImportStorageKey: 'original-canvas',
    }));
    const session = await createCoursewareGenerationSession(
      { ...options, conversionMode },
      read,
      prepare,
    );
    expect(read).not.toHaveBeenCalled();
    expect(prepare).toHaveBeenCalledOnce();
    expect(session.conversionMode).toBe(conversionMode);
    expect(session.previewPhase).toBe('ppt-review');
    expect(session.pptxImportStorageKey).toBe('original-canvas');
    expect(session.requirements.requirement).toContain('解释边界条件');
    expect(session.requirements.targetDurationMinutes).toBe(28);
  },
);

it('rejects a faithful request lacking a reusable original canvas instead of silently enhancing it', async () => {
  await expect(
    createCoursewareGenerationSession({ ...options, conversionMode: 'faithful' }, vi.fn()),
  ).rejects.toThrow('原始 PPTX');
  await expect(
    createCoursewareGenerationSession(
      {
        ...options,
        conversionMode: 'faithful',
        course: { ...course, materials: [{ ...course.materials[0], name: '旧课件.ppt' }] },
      },
      vi.fn(),
    ),
  ).rejects.toThrow('原始 PPTX');
});
