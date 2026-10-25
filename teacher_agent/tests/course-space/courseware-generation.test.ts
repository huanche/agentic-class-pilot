import { describe, expect, it, vi } from 'vitest';
import {
  createCoursewareGenerationSession,
  defaultCoursewareMaterialIds,
} from '@/lib/course-space/courseware-generation';
import type {
  CourseMaterialExtraction,
  CourseMaterialRecord,
  CourseSpace,
} from '@/lib/course-space';
import { buildInitialCourseGovernance } from '@/lib/course-governance/governance';

const material = (
  id: string,
  status: CourseMaterialRecord['status'] = 'ready',
): CourseMaterialRecord => ({
  id,
  name: `${id}.txt`,
  status,
  teacherId: 'teacher',
  courseId: 'course',
  mimeType: 'text/plain',
  size: 10,
  storageKey: id,
  createdAt: 1,
  updatedAt: 1,
});
const course = (): CourseSpace => ({
  id: 'course',
  title: 'Python',
  teacherId: 'teacher',
  status: 'draft',
  createdAt: 1,
  updatedAt: 1,
  materials: [
    material('shared'),
    material('one'),
    material('two'),
    material('pending', 'uploaded'),
  ],
  modules: [
    {
      id: 'week',
      courseId: 'course',
      title: '第1周',
      order: 1,
      objectives: [],
      createdAt: 1,
      updatedAt: 1,
      lessons: ['one', 'two'].map((id, index) => ({
        id,
        moduleId: 'week',
        title: index === 0 ? '变量与类型' : '条件分支',
        order: index + 1,
        objectives: index === 0 ? ['区分整数和字符串'] : [],
        materialIds: [id],
        createdAt: 1,
        updatedAt: 1,
        files: [
          {
            id: `${id}-notes`,
            lessonId: id,
            type: 'knowledge-points',
            title: '本课知识点',
            content: index === 0 ? 'input 返回字符串' : 'if 语句',
            status: 'ready',
            createdAt: 1,
            updatedAt: 1,
          },
        ],
      })),
    },
  ],
});
const extraction = (id: string, text = `${id}的正文`) =>
  ({ materialId: id, text }) as CourseMaterialExtraction;
const read = vi.fn(async (id: string) => extraction(id));
const options = () => ({
  course: course(),
  scope: { type: 'lesson' as const, lessonId: 'one' },
  sessionId: 'session',
  materialIds: ['one'],
  targetDurationMinutes: '',
  instruction: '',
});

describe('lesson courseware source selection and outline handoff', () => {
  it('defaults to sources linked to the selected lesson', () => {
    expect(defaultCoursewareMaterialIds(course(), { type: 'lesson', lessonId: 'one' })).toEqual([
      'one',
    ]);
    expect(defaultCoursewareMaterialIds(course(), { type: 'lesson', lessonId: 'two' })).toEqual([
      'two',
    ]);
  });

  it('falls back to shared course sources without borrowing another lesson source', () => {
    const input = course();
    input.modules[0].lessons[0].materialIds = [];
    // Keep the old source explicitly assigned to another lesson.
    input.modules[0].lessons[1].materialIds.push('one');
    expect(defaultCoursewareMaterialIds(input, { type: 'lesson', lessonId: 'one' })).toEqual([
      'shared',
    ]);
  });

  it('defaults modules to their linked sources and the course to all ready sources', () => {
    expect(defaultCoursewareMaterialIds(course(), { type: 'module', moduleId: 'week' })).toEqual([
      'one',
      'two',
    ]);
    expect(defaultCoursewareMaterialIds(course(), { type: 'course' })).toEqual([
      'shared',
      'one',
      'two',
    ]);
  });

  it('asks the teacher to choose when multiple unrelated shared sources are available', () => {
    const input = course();
    input.modules[0].lessons[0].materialIds = [];
    expect(defaultCoursewareMaterialIds(input, { type: 'lesson', lessonId: 'one' })).toEqual([]);
  });

  it('loads only the explicitly selected sources, retaining their order and all content', async () => {
    const load = vi.fn(async (id: string) => extraction(id));
    const session = await createCoursewareGenerationSession(
      { ...options(), materialIds: ['two', 'shared', 'two'] },
      load,
    );
    expect(load.mock.calls.map(([id]) => id)).toEqual(['two', 'shared']);
    expect(session.pdfText).toBe('【two.txt】\ntwo的正文\n\n【shared.txt】\nshared的正文');
    expect(session.courseSpaceContext).toEqual({
      courseId: 'course',
      scope: options().scope,
      materialIds: ['two', 'shared'],
    });
  });

  it('passes lesson scope, approved knowledge, supplementary requirements and the 28 minute default together', async () => {
    const session = await createCoursewareGenerationSession(
      { ...options(), instruction: '增加一个计算器案例' },
      read,
    );
    expect(session.requirements.targetDurationMinutes).toBe(28);
    expect(session.requirements.requirement).toContain('Python / 第1周 / 变量与类型');
    expect(session.requirements.requirement).toContain('区分整数和字符串');
    expect(session.requirements.requirement).toContain('input 返回字符串');
    expect(session.requirements.requirement).toContain('增加一个计算器案例');
    expect(session.requirements.requirement).not.toContain('if 语句');
    expect(session.previewPhase).toBe('preparing');
    expect(session.sceneOutlines).toBeUndefined();
  });

  it.each(['讲义.pdf', '旧课件.PPT', '资料.pptx'])(
    'provides a source fingerprint for enhanced extracted material %s without a PPTX canvas',
    async (name) => {
      const input = options();
      input.course.materials[1].name = name;
      const session = await createCoursewareGenerationSession(input, read);
      expect(session.sourceFingerprint?.sha256).toMatch(/^[a-f0-9]{64}$/);
      const record = buildInitialCourseGovernance({
        stageId: 'regression',
        mode: session.conversionMode!,
        source: session.sourceFingerprint!,
        outlines: [
          {
            id: 'page',
            title: '变量',
            type: 'slide',
            order: 1,
            description: '区分变量类型',
            keyPoints: [],
          },
        ],
      });
      expect(record.sceneReviews[0].sourceRefs[0].sourceSha256).toBe(
        session.sourceFingerprint?.sha256,
      );
    },
  );

  it('preserves a teacher-selected duration instead of replacing it with the default', async () => {
    const session = await createCoursewareGenerationSession(
      { ...options(), targetDurationMinutes: '20' },
      read,
    );
    expect(session.requirements.targetDurationMinutes).toBe(20);
  });

  it('never silently drops the seventh selected file', async () => {
    const input = options();
    input.course.materials = Array.from({ length: 7 }, (_, index) => material(`source${index}`));
    input.materialIds = input.course.materials.map((item) => item.id);
    const session = await createCoursewareGenerationSession(input, read);
    expect(session.pdfText).toContain('source6的正文');
  });

  it.each(['missing', 'pending'])(
    'rejects deleted or unparsed selected material %s before reading',
    async (id) => {
      const load = vi.fn();
      await expect(
        createCoursewareGenerationSession({ ...options(), materialIds: [id] }, load),
      ).rejects.toThrow('重新选择');
      expect(load).not.toHaveBeenCalled();
    },
  );

  it('blocks generation with no sources or an invalid duration', async () => {
    await expect(
      createCoursewareGenerationSession({ ...options(), materialIds: [] }, read),
    ).rejects.toThrow('至少一份');
    await expect(
      createCoursewareGenerationSession({ ...options(), targetDurationMinutes: '0' }, read),
    ).rejects.toThrow('正整数');
  });

  it('reports a source read failure instead of generating from partial materials', async () => {
    await expect(
      createCoursewareGenerationSession(options(), async () => {
        throw new Error('404');
      }),
    ).rejects.toThrow('读取“one.txt”失败');
    await expect(
      createCoursewareGenerationSession(options(), async () => extraction('one', '')),
    ).rejects.toThrow('没有可用的解析正文');
    await expect(
      createCoursewareGenerationSession(options(), async () => extraction('two')),
    ).rejects.toThrow('没有可用的解析正文');
  });

  it('does not silently truncate an oversized source', async () => {
    await expect(
      createCoursewareGenerationSession(options(), async () =>
        extraction('one', '文'.repeat(60001)),
      ),
    ).rejects.toThrow('超过 6 万字');
  });

  it('rejects a stale lesson selection and keeps draft notes out of the model input', async () => {
    expect(() =>
      defaultCoursewareMaterialIds(course(), { type: 'lesson', lessonId: 'deleted' }),
    ).toThrow('不存在');
    const input = options();
    input.course.modules[0].lessons[0].files![0].status = 'draft';
    const session = await createCoursewareGenerationSession(input, read);
    expect(session.requirements.requirement).not.toContain('input 返回字符串');
  });
});
