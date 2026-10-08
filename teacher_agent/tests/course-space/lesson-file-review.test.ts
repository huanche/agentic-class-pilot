import { createHash } from 'node:crypto';
import { NextRequest } from 'next/server';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { CourseLesson, CourseLessonFileType, CourseSpace } from '@/lib/course-space/types';

type CourseUpdater = (course: CourseSpace) => CourseSpace | Promise<CourseSpace>;
const mocks = vi.hoisted(() => ({
  readServerCourse: vi.fn<(id: string) => Promise<CourseSpace | null>>(),
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

// Exercise the real route, generator and title map; only external boundaries are mocked.
import { PATCH, POST } from '@/app/api/course-space/[courseId]/lesson-files/draft/route';
import { lessonFileTitles } from '@/lib/server/teacher-course-operations';

const allTypes = Object.keys(lessonFileTitles) as CourseLessonFileType[];
const context = { params: Promise.resolve({ courseId: 'course-review' }) };
const now = 1800000000000;
const generated = Object.fromEntries(allTypes.map((type) => [type, `  审核草稿：${type}  `]));
type Review = {
  lessonId: string;
  baseVersion: string;
  drafts: Array<{ type: CourseLessonFileType; title: string; content: string }>;
};

function fixture(): CourseSpace {
  return {
    id: 'course-review', teacherId: 'teacher-review', title: '测试课程', status: 'draft',
    materials: [], createdAt: 1, updatedAt: 2,
    modules: [
      {
        id: 'm1', courseId: 'course-review', title: '第一模块', order: 0, objectives: [],
        createdAt: 1, updatedAt: 2,
        lessons: ['l1', 'l2'].map((id, index) => ({
          id, moduleId: 'm1', title: `第${index + 1}周`, order: index, objectives: [],
          materialIds: [], createdAt: 1, updatedAt: 2,
          files: [{
            id: `original-${id}`, lessonId: id, type: 'lesson-objectives', title: '原目标',
            content: `已审核旧正文 ${id}`, status: 'ready', createdAt: 10, updatedAt: 20,
          }, {
            id: `untouched-${id}`, lessonId: id, type: 'exercises', title: '原习题',
            content: '不得修改的习题', status: 'ready', createdAt: 11, updatedAt: 21,
            classVisible: true, classPublicationId: `publication-${id}`, classPublishedAt: 22,
          }],
        })),
      },
      {
        id: 'm2', courseId: 'course-review', title: '无关模块', order: 1, objectives: [],
        createdAt: 1, updatedAt: 2,
        lessons: [{
          id: 'l3', moduleId: 'm2', title: '第3周', order: 0, objectives: [], materialIds: [],
          createdAt: 1, updatedAt: 2,
        }],
      },
    ],
  } satisfies CourseSpace;
}

let stored: CourseSpace;
function lesson(id: string): CourseLesson {
  const found = stored.modules.flatMap((module) => module.lessons).find((item) => item.id === id);
  if (!found) throw new Error(`Missing test lesson: ${id}`);
  return found;
}
function request(method: 'POST' | 'PATCH', body: unknown) {
  return new NextRequest('http://localhost/api/course-space/course-review/lesson-files/draft', {
    method, headers: { 'content-type': 'application/json' }, body: JSON.stringify(body),
  });
}
async function draft(lessonId = 'l1', fileTypes: CourseLessonFileType[] = ['lesson-objectives']): Promise<Review> {
  const response = await POST(request('POST', { lessonId, fileTypes }), context);
  expect(response.status).toBe(200);
  const body = await response.json();
  expect(body.success).toBe(true);
  return { lessonId: body.lessonId, baseVersion: body.baseVersion, drafts: body.drafts };
}
async function expectRejected(body: unknown, status = 400) {
  const before = structuredClone(stored);
  const response = await PATCH(request('PATCH', body), context);
  expect(response.status).toBe(status);
  expect(await response.json()).toMatchObject({ success: false, error: expect.any(String) });
  expect(stored).toEqual(before);
  expect(mocks.persist).not.toHaveBeenCalled();
  return response;
}

describe('lesson file draft review API', () => {
  afterEach(() => vi.restoreAllMocks());

  beforeEach(() => {
    vi.resetAllMocks();
    stored = fixture();
    vi.spyOn(Date, 'now').mockReturnValue(now);
    mocks.readServerCourse.mockImplementation(async () => structuredClone(stored));
    mocks.updateServerCourse.mockImplementation(async (id, update) => {
      expect(id).toBe(stored.id);
      // Pass the live object: a callback that mutates early must fail the no-write assertions.
      // Persist only after the complete callback succeeds, like updateServerCourse's lock/save.
      const updated = await update(stored);
      mocks.persist(updated);
      stored = updated;
      return structuredClone(updated);
    });
    mocks.resolveModel.mockResolvedValue({ model: { id: 'mock-model' }, thinkingConfig: undefined });
    mocks.callLLM.mockResolvedValue({ text: JSON.stringify(generated) });
  });

  it('retains publication metadata when updating an already published file', async () => {
    const original = lesson('l1').files![0];
    Object.assign(original, { classVisible: true, classPublicationId: 'release-a', classPublishedAt: 42 });
    const review = await draft();
    const response = await PATCH(request('PATCH', review), context);
    expect(response.status).toBe(200);
    expect(lesson('l1').files![0]).toMatchObject({
      id: original.id, createdAt: original.createdAt,
      classVisible: true, classPublicationId: 'release-a', classPublishedAt: 42,
      content: '审核草稿：lesson-objectives',
    });
  });

  it('generates all seven real file types with titles and an exact SHA-256 snapshot, without overwriting', async () => {
    expect(allTypes).toEqual([
      'lesson-objectives', 'knowledge-points', 'teaching-activities', 'courseware-pages',
      'narration-segments', 'exercises', 'assessment-criteria',
    ]);
    const before = structuredClone(stored);
    const review = await draft('l1', allTypes);
    const selectedState = [...allTypes].sort().map((type) => ({
      type, files: before.modules[0].lessons[0].files!.filter((file) => file.type === type),
    }));
    expect(review.baseVersion).toBe(createHash('sha256').update(JSON.stringify(selectedState)).digest('hex'));
    expect(review.drafts).toEqual(allTypes.map((type) => ({
      type, title: lessonFileTitles[type], content: `审核草稿：${type}`,
    })));
    expect(mocks.callLLM).toHaveBeenCalledOnce();
    expect(stored).toEqual(before);
    expect(mocks.updateServerCourse).not.toHaveBeenCalled();
    expect(mocks.persist).not.toHaveBeenCalled();
  });

  it('supports single-lesson approval, preserves id/createdAt and leaves unrelated files and lessons unchanged', async () => {
    const before = structuredClone(stored);
    const review = await draft('l1', ['lesson-objectives', 'knowledge-points']);
    review.drafts[0].content = '  教师修改后的目标  ';
    const response = await PATCH(request('PATCH', review), context);
    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body).toMatchObject({ success: true, lessons: [{ lessonId: 'l1' }] });
    expect(body.files).toEqual(body.lessons[0].files);
    expect(body.files).toHaveLength(2);
    expect(lesson('l1').files?.find((file) => file.type === 'lesson-objectives')).toEqual({
      id: 'original-l1', lessonId: 'l1', type: 'lesson-objectives', title: lessonFileTitles['lesson-objectives'],
      content: '教师修改后的目标', status: 'ready', createdAt: 10, updatedAt: now,
    });
    expect(lesson('l1').files?.find((file) => file.type === 'knowledge-points')).toMatchObject({
      id: expect.any(String), lessonId: 'l1', status: 'ready', createdAt: now, updatedAt: now,
    });
    expect(lesson('l1').files?.find((file) => file.type === 'exercises')).toEqual(before.modules[0].lessons[0].files![1]);
    expect(lesson('l2')).toEqual(before.modules[0].lessons[1]);
    expect(stored.modules[1]).toEqual(before.modules[1]);
    expect(stored.updatedAt).toBe(now);
    expect(mocks.updateServerCourse).toHaveBeenCalledOnce();
    expect(mocks.persist).toHaveBeenCalledOnce();
  });

  it('approves all seven types in a single write and retains existing file identities', async () => {
    const review = await draft('l1', allTypes);
    const response = await PATCH(request('PATCH', { lessons: [review] }), context);
    expect(response.status).toBe(200);
    expect(lesson('l1').files).toHaveLength(7);
    expect(new Set(lesson('l1').files?.map((file) => file.type))).toEqual(new Set(allTypes));
    expect(new Set(lesson('l1').files?.map((file) => file.id)).size).toBe(7);
    for (const type of allTypes) {
      expect(lesson('l1').files?.find((file) => file.type === type)).toMatchObject({
        lessonId: 'l1', title: lessonFileTitles[type], content: `审核草稿：${type}`, status: 'ready',
      });
    }
    expect(lesson('l1').files?.find((file) => file.type === 'exercises')).toMatchObject({ id: 'untouched-l1', createdAt: 11 });
    expect(mocks.persist).toHaveBeenCalledOnce();
  });

  it('generates multiple lessons without writes, then approves the entire batch with one update', async () => {
    const before = structuredClone(stored);
    const reviews = [await draft('l1'), await draft('l2')];
    expect(stored).toEqual(before);
    expect(mocks.persist).not.toHaveBeenCalled();
    const response = await PATCH(request('PATCH', { lessons: reviews }), context);
    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body.lessons.map((item: { lessonId: string }) => item.lessonId)).toEqual(['l1', 'l2']);
    expect(body.files).toBeUndefined();
    for (const id of ['l1', 'l2']) {
      expect(lesson(id).files![0]).toMatchObject({
        id: `original-${id}`, createdAt: 10, content: '审核草稿：lesson-objectives',
      });
      expect(lesson(id).files![1]).toEqual(before.modules[0].lessons.find((item) => item.id === id)!.files![1]);
    }
    expect(stored.modules[1]).toEqual(before.modules[1]);
    expect(mocks.updateServerCourse).toHaveBeenCalledOnce();
    expect(mocks.persist).toHaveBeenCalledOnce();
  });

  it('leaves every existing file unchanged when review is cancelled without PATCH (API contract, not UI)', async () => {
    const before = structuredClone(stored);
    const patch = vi.fn(PATCH);
    const pendingReviews = [await draft('l1', allTypes), await draft('l2', allTypes)];
    // Cancellation discards client-held drafts; it must not submit the approval endpoint.
    pendingReviews.splice(0);
    expect(pendingReviews).toEqual([]);
    expect(patch).not.toHaveBeenCalled();
    expect(mocks.updateServerCourse).not.toHaveBeenCalled();
    expect(mocks.persist).not.toHaveBeenCalled();
    expect(stored).toEqual(before);
  });

  it('does not save an earlier lesson when later draft generation fails', async () => {
    const before = structuredClone(stored);
    await draft('l1');
    mocks.callLLM.mockRejectedValueOnce(new Error('mock generation failure'));
    const response = await POST(request('POST', { lessonId: 'l2', fileTypes: allTypes }), context);
    expect(response.status).toBe(500);
    expect(await response.json()).toMatchObject({ success: false });
    expect(stored).toEqual(before);
    expect(mocks.updateServerCourse).not.toHaveBeenCalled();
    expect(mocks.persist).not.toHaveBeenCalled();
  });

  it.each([
    ['missing requested content', {}],
    ['whitespace content', { 'lesson-objectives': '   ' }],
    ['non-string content', { 'lesson-objectives': 123 }],
    ['oversized content', { 'lesson-objectives': 'x'.repeat(30001) }],
  ])('rejects %s from generation without writing', async (_label, output) => {
    const before = structuredClone(stored);
    mocks.callLLM.mockResolvedValueOnce({ text: JSON.stringify(output) });
    const response = await POST(request('POST', { lessonId: 'l1', fileTypes: ['lesson-objectives'] }), context);
    expect(response.status).toBe(500);
    expect(await response.json()).toMatchObject({ success: false });
    expect(stored).toEqual(before);
    expect(mocks.updateServerCourse).not.toHaveBeenCalled();
  });

  it.each([
    ['null body', null], ['array body', []],
    ['empty types', { lessonId: 'l1', fileTypes: [] }],
    ['duplicate types', { lessonId: 'l1', fileTypes: ['exercises', 'exercises'] }],
    ['unknown type', { lessonId: 'l1', fileTypes: ['invalid'] }],
    ['null types', { lessonId: 'l1', fileTypes: null }],
    ['null type', { lessonId: 'l1', fileTypes: [null] }],
    ['missing lesson', { fileTypes: ['exercises'] }],
    ['null lesson', { lessonId: null, fileTypes: ['exercises'] }],
    ['null instruction', { lessonId: 'l1', fileTypes: ['exercises'], instruction: null }],
  ])('rejects POST %s before generation', async (_label, body) => {
    const before = structuredClone(stored);
    const response = await POST(request('POST', body), context);
    expect(response.status).toBe(400);
    expect(await response.json()).toMatchObject({ success: false });
    expect(mocks.callLLM).not.toHaveBeenCalled();
    expect(mocks.updateServerCourse).not.toHaveBeenCalled();
    expect(stored).toEqual(before);
  });

  it.each(['missing-lesson', 'missing-course'])('rejects POST for %s without generation or writes', async (target) => {
    if (target === 'missing-course') mocks.readServerCourse.mockResolvedValueOnce(null);
    const response = await POST(request('POST', {
      lessonId: target === 'missing-lesson' ? 'wrong-id' : 'l1', fileTypes: ['exercises'],
    }), context);
    expect(response.status).toBe(404);
    expect(mocks.callLLM).not.toHaveBeenCalled();
    expect(mocks.updateServerCourse).not.toHaveBeenCalled();
  });

  it.each([
    ['null body', null], ['array body', []], ['null lessons', { lessons: null }],
    ['empty batch', { lessons: [] }], ['non-array lessons', { lessons: {} }],
    ['null lesson entry', { lessons: [null] }],
  ])('rejects PATCH %s before invoking the updater', async (_label, body) => {
    await expectRejected(body);
    expect(mocks.updateServerCourse).not.toHaveBeenCalled();
  });

  it('rejects more than 100 lessons before invoking the updater', async () => {
    const review = await draft();
    await expectRejected({ lessons: Array.from({ length: 101 }, (_, index) => ({ ...review, lessonId: `l${index}` })) });
    expect(mocks.updateServerCourse).not.toHaveBeenCalled();
  });

  it('rejects duplicate lessons before invoking the updater', async () => {
    const review = await draft();
    await expectRejected({ lessons: [review, review] });
    expect(mocks.updateServerCourse).not.toHaveBeenCalled();
  });

  it.each([
    ['duplicate file types', [{ type: 'lesson-objectives', content: 'a' }, { type: 'lesson-objectives', content: 'b' }]],
    ['illegal type', [{ type: 'invalid', content: 'a' }]],
    ['empty drafts', []], ['null drafts', null], ['null draft entry', [null]],
    ['null file type', [{ type: null, content: 'a' }]],
    ['empty content', [{ type: 'lesson-objectives', content: '' }]],
    ['whitespace content', [{ type: 'lesson-objectives', content: ' \n ' }]],
    ['null content', [{ type: 'lesson-objectives', content: null }]],
    ['non-string content', [{ type: 'lesson-objectives', content: 123 }]],
    ['oversized content', [{ type: 'lesson-objectives', content: 'x'.repeat(30001) }]],
  ])('validates the whole batch before saving: later lesson has %s', async (_label, invalidDrafts) => {
    const reviews = [await draft('l1'), await draft('l2')];
    await expectRejected({ lessons: [reviews[0], { ...reviews[1], drafts: invalidDrafts }] });
    expect(mocks.updateServerCourse).not.toHaveBeenCalled();
  });

  it.each([
    ['null lesson id', { lessonId: null }], ['empty lesson id', { lessonId: '' }],
    ['null version', { baseVersion: null }], ['invalid version', { baseVersion: 'not-sha256' }],
    ['uppercase version', { baseVersion: 'A'.repeat(64) }],
  ])('rejects %s before invoking the updater', async (_label, overrides) => {
    await expectRejected({ ...await draft(), ...overrides });
    expect(mocks.updateServerCourse).not.toHaveBeenCalled();
  });

  it('accepts the 30000-character approval boundary', async () => {
    const review = await draft();
    review.drafts[0].content = 'x'.repeat(30000);
    const response = await PATCH(request('PATCH', review), context);
    expect(response.status).toBe(200);
    expect(lesson('l1').files![0].content).toHaveLength(30000);
    expect(mocks.persist).toHaveBeenCalledOnce();
  });

  it.each(['content', 'addition', 'removal'] as const)('returns 409 with no write when selected file state changes: %s', async (change) => {
    const review = await draft('l1', ['lesson-objectives', 'knowledge-points']);
    if (change === 'content') lesson('l1').files![0].content = '其他教师的新正文';
    if (change === 'removal') lesson('l1').files!.splice(0, 1);
    if (change === 'addition') lesson('l1').files!.push({
      id: 'concurrent-file', lessonId: 'l1', type: 'knowledge-points', title: '并发知识点',
      content: '并发新增', status: 'ready', createdAt: 30, updatedAt: 30,
    });
    await expectRejected(review, 409);
    expect(mocks.updateServerCourse).toHaveBeenCalledOnce();
  });

  it('checks the captured version against edits made during generation', async () => {
    mocks.callLLM.mockImplementationOnce(async () => {
      lesson('l1').files![0].content = '生成过程中保存的新正文';
      return { text: JSON.stringify(generated) };
    });
    const review = await draft();
    await expectRejected(review, 409);
    expect(lesson('l1').files![0].content).toBe('生成过程中保存的新正文');
  });

  it('allows unrelated file edits after generation and does not overwrite them', async () => {
    const review = await draft();
    lesson('l1').files![1].content = '并发更新的无关习题';
    const unrelated = structuredClone(lesson('l1').files![1]);
    const response = await PATCH(request('PATCH', review), context);
    expect(response.status).toBe(200);
    expect(lesson('l1').files![1]).toEqual(unrelated);
  });

  it.each(['changed-file', 'deleted-lesson', 'wrong-lesson'])('validates every lesson before mutation when the later lesson has %s', async (failure) => {
    const reviews = [await draft('l1'), await draft('l2')];
    if (failure === 'changed-file') lesson('l2').files![0].content = '并发修改';
    if (failure === 'deleted-lesson') stored.modules[0].lessons.splice(1, 1);
    if (failure === 'wrong-lesson') reviews[1].lessonId = 'wrong-id';
    await expectRejected({ lessons: reviews }, 409);
    expect(lesson('l1').files![0].content).toBe('已审核旧正文 l1');
    expect(mocks.updateServerCourse).toHaveBeenCalledOnce();
  });

  it('returns 409 without persistence when the single target lesson was deleted', async () => {
    const review = await draft();
    stored.modules[0].lessons.splice(0, 1);
    await expectRejected(review, 409);
  });
});