import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { CourseLessonFileType, CourseSpace } from '@/lib/course-space/types';
import type { TeacherOperationPlan } from '@/lib/course-space/teacher-agent-intent';

type CourseUpdater = (course: CourseSpace) => CourseSpace | Promise<CourseSpace>;
const mocks = vi.hoisted(() => ({
  readServerCourse: vi.fn(),
  updateServerCourse: vi.fn<(id: string, update: CourseUpdater) => Promise<CourseSpace>>(),
  persist: vi.fn<(course: CourseSpace) => void>(),
  readMaterialExtraction: vi.fn(),
  listCourseArtifacts: vi.fn(),
  saveCourseArtifact: vi.fn(),
  deleteCourseArtifact: vi.fn(),
  callLLM: vi.fn(),
  resolveModel: vi.fn(),
}));
vi.mock('@/lib/server/course-space-storage', () => ({
  readServerCourse: mocks.readServerCourse,
  updateServerCourse: mocks.updateServerCourse,
  readMaterialExtraction: mocks.readMaterialExtraction,
  listCourseArtifacts: mocks.listCourseArtifacts,
  saveCourseArtifact: mocks.saveCourseArtifact,
  deleteCourseArtifact: mocks.deleteCourseArtifact,
}));
vi.mock('@/lib/ai/llm', () => ({ callLLM: mocks.callLLM }));
vi.mock('@/lib/server/resolve-model', () => ({ resolveModel: mocks.resolveModel }));

import { executeConfirmedTeacherPlan, lessonFileTitles } from '@/lib/server/teacher-course-operations';
import { planTeacherWorkspaceOperation } from '@/lib/course-space/teacher-agent-intent';

const allTypes = Object.keys(lessonFileTitles) as CourseLessonFileType[];
const now = 1800000000000;
function fixture(): CourseSpace {
  return {
    id: 'course-review', teacherId: 'teacher-review', title: '测试课程', status: 'draft',
    materials: [], createdAt: 1, updatedAt: 2,
    modules: [{
      id: 'm1', courseId: 'course-review', title: '第一模块', order: 0, objectives: [],
      createdAt: 1, updatedAt: 2,
      lessons: ['l1', 'l2', 'l3'].map((id, index) => ({
        id, moduleId: 'm1', title: `第${index + 1}周`, order: index, objectives: [], materialIds: [],
        createdAt: 1, updatedAt: 2,
        files: [{
          id: `old-${id}`, lessonId: id, type: 'lesson-objectives', title: '教师原目标',
          content: '教师已经审核的旧正文', status: 'ready', createdAt: 10, updatedAt: 20,
          classVisible: true, classPublicationId: `publication-${id}`, classPublishedAt: 21,
        }],
      })),
    }],
  } satisfies CourseSpace;
}
function plan(options: {
  populateContent?: boolean;
  requiresConfirmation?: boolean;
  lessonIds?: string[];
  fileTypes?: CourseLessonFileType[];
} = {}): TeacherOperationPlan {
  return {
    id: 'review-plan', kind: 'create-lesson-files', title: '创建课时文件', summary: '测试审核流程',
    requiresConfirmation: options.requiresConfirmation ?? true, status: 'planned',
    steps: [{ id: 'create', tool: 'course.structure', label: '创建文件', status: 'pending' }],
    action: {
      type: 'create-lesson-files', label: '创建课时文件', lessonIds: options.lessonIds ?? ['l1'],
      fileTypes: options.fileTypes ?? allTypes, populateContent: options.populateContent,
      instruction: '不能绕过教师审核直接覆盖正文',
    },
  };
}

let stored: CourseSpace;
function expectNoExternalWork() {
  expect(mocks.callLLM).not.toHaveBeenCalled();
  expect(mocks.resolveModel).not.toHaveBeenCalled();
  expect(mocks.readMaterialExtraction).not.toHaveBeenCalled();
  expect(mocks.readServerCourse).not.toHaveBeenCalled();
  expect(mocks.listCourseArtifacts).not.toHaveBeenCalled();
  expect(mocks.saveCourseArtifact).not.toHaveBeenCalled();
  expect(mocks.deleteCourseArtifact).not.toHaveBeenCalled();
}

describe('teacher operation review enforcement', () => {
  afterEach(() => vi.restoreAllMocks());

  beforeEach(() => {
    vi.resetAllMocks();
    stored = fixture();
    vi.spyOn(Date, 'now').mockReturnValue(now);
    mocks.updateServerCourse.mockImplementation(async (id, update) => {
      expect(id).toBe(stored.id);
      // Do not clone before the callback: catch mutations even if validation throws later.
      const updated = await update(stored);
      mocks.persist(updated);
      stored = updated;
      return structuredClone(updated);
    });
  });

  it.each([
    { name: 'confirmed single lesson', requiresConfirmation: true, lessonIds: ['l1'] },
    { name: 'confirmed multiple lessons', requiresConfirmation: true, lessonIds: ['l1', 'l2'] },
    { name: 'legacy forged auto-execution single lesson', requiresConfirmation: false, lessonIds: ['l1'] },
    { name: 'legacy forged auto-execution multiple lessons', requiresConfirmation: false, lessonIds: ['l1', 'l2'] },
  ])('rejects populateContent for $name before any generation or write', async (options) => {
    const before = structuredClone(stored);
    const operation = plan({ ...options, populateContent: true });
    const originalPlan = structuredClone(operation);
    await expect(executeConfirmedTeacherPlan(stored.id, operation)).rejects.toThrow(
      '课时内容必须通过草稿生成与教师审核页面保存，不能直接执行写入',
    );
    expect(stored).toEqual(before);
    expect(operation).toEqual(originalPlan);
    expect(mocks.updateServerCourse).not.toHaveBeenCalled();
    expect(mocks.persist).not.toHaveBeenCalled();
    expectNoExternalWork();
  });

  it.each(allTypes)('rejects direct population of %s, including a forged requiresConfirmation=false plan', async (type) => {
    const before = structuredClone(stored);
    await expect(executeConfirmedTeacherPlan(stored.id, plan({
      populateContent: true, requiresConfirmation: false, fileTypes: [type],
    }))).rejects.toThrow(/草稿生成与教师审核/);
    expect(stored).toEqual(before);
    expect(mocks.updateServerCourse).not.toHaveBeenCalled();
    expect(mocks.persist).not.toHaveBeenCalled();
    expectNoExternalWork();
  });

  it('requires confirmation for newly planned single- and multiple-lesson content generation', () => {
    const before = structuredClone(stored);
    for (const message of [
      '请为第1周生成课时目标文件，并根据课程材料填写具体内容',
      '请为1-2周生成课时目标、知识点文件，并根据课程材料填写具体内容',
    ]) {
      const operation = planTeacherWorkspaceOperation(message, stored);
      expect(operation).toMatchObject({
        kind: 'create-lesson-files', requiresConfirmation: true, status: 'planned',
        action: { type: 'create-lesson-files', populateContent: true },
      });
      expect(operation?.action).toMatchObject({
        lessonIds: message.includes('1-2周') ? ['l1', 'l2'] : ['l1'],
      });
    }
    expect(stored).toEqual(before);
    expect(mocks.updateServerCourse).not.toHaveBeenCalled();
    expectNoExternalWork();
  });

  it.each([false, undefined])('creates only missing empty files when populateContent=%s, retaining all existing fields', async (populateContent) => {
    const before = structuredClone(stored);
    const operation = plan({ populateContent, lessonIds: ['l1', 'l2'] });
    const result = await executeConfirmedTeacherPlan(stored.id, operation);
    expect(result.plan).toMatchObject({
      status: 'completed', result: '已创建 12 个课时结构文件；已有同类型文件已自动跳过。',
      steps: [{ id: 'create', status: 'completed' }],
    });
    expect(result.dispatch).toBeUndefined();
    for (let index = 0; index < 2; index++) {
      const current = stored.modules[0].lessons[index];
      expect(current.files).toHaveLength(7);
      expect(current.files![0]).toEqual(before.modules[0].lessons[index].files![0]);
      expect(new Set(current.files?.map((file) => file.type))).toEqual(new Set(allTypes));
      for (const file of current.files!.slice(1)) {
        expect(file).toMatchObject({
          lessonId: current.id, title: lessonFileTitles[file.type], content: '', status: 'draft',
          createdAt: now, updatedAt: now,
        });
      }
    }
    const ids = stored.modules[0].lessons.slice(0, 2).flatMap((lesson) => lesson.files!.map((file) => file.id));
    expect(new Set(ids).size).toBe(14);
    expect(stored.modules[0].lessons[2]).toEqual(before.modules[0].lessons[2]);
    expect(mocks.updateServerCourse).toHaveBeenCalledOnce();
    expect(mocks.persist).toHaveBeenCalledOnce();
    expectNoExternalWork();
  });

  it('does not replace an existing ready file when only its type was requested', async () => {
    const original = structuredClone(stored.modules[0].lessons[0].files);
    const result = await executeConfirmedTeacherPlan(stored.id, plan({
      populateContent: false, fileTypes: ['lesson-objectives'],
    }));
    expect(result.plan.result).toContain('已创建 0 个');
    expect(stored.modules[0].lessons[0].files).toEqual(original);
    expectNoExternalWork();
  });

  it('is idempotent for repeated empty-file creation and preserves reviewed contents', async () => {
    const operation = plan({ populateContent: false });
    await executeConfirmedTeacherPlan(stored.id, operation);
    const files = structuredClone(stored.modules[0].lessons[0].files);
    const result = await executeConfirmedTeacherPlan(stored.id, operation);
    expect(result.plan.result).toContain('已创建 0 个');
    expect(stored.modules[0].lessons[0].files).toEqual(files);
    expect(mocks.persist).toHaveBeenCalledTimes(2);
    expectNoExternalWork();
  });

  it('creates empty files for a lesson with no files without touching the other lessons', async () => {
    delete stored.modules[0].lessons[1].files;
    const before = structuredClone(stored);
    await executeConfirmedTeacherPlan(stored.id, plan({ populateContent: false, lessonIds: ['l2'] }));
    const files = stored.modules[0].lessons[1].files!;
    expect(files).toHaveLength(7);
    expect(files.every((file) => file.content === '' && file.status === 'draft')).toBe(true);
    expect(stored.modules[0].lessons[0]).toEqual(before.modules[0].lessons[0]);
    expect(stored.modules[0].lessons[2]).toEqual(before.modules[0].lessons[2]);
    expect(mocks.persist).toHaveBeenCalledOnce();
    expectNoExternalWork();
  });

  it('validates all target lessons before adding any empty files', async () => {
    const before = structuredClone(stored);
    await expect(executeConfirmedTeacherPlan(stored.id, plan({
      populateContent: false, lessonIds: ['l1', 'deleted-lesson'],
    }))).rejects.toThrow('部分目标课时已变化，请重新生成操作计划');
    expect(stored).toEqual(before);
    expect(mocks.updateServerCourse).toHaveBeenCalledOnce();
    expect(mocks.persist).not.toHaveBeenCalled();
    expectNoExternalWork();
  });
});