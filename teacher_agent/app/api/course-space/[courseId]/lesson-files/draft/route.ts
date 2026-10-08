import { createHash } from 'node:crypto';
import { NextRequest, NextResponse } from 'next/server';
import type { CourseLesson } from '@/lib/course-space/types';
import { readServerCourse, updateServerCourse } from '@/lib/server/course-space-storage';
import { generateLessonFileContent, lessonFileTitles } from '@/lib/server/teacher-course-operations';

export const runtime = 'nodejs';
export const maxDuration = 180;

type DraftType = keyof typeof lessonFileTitles;
type Draft = { type: DraftType; content: string };
type ReviewedLesson = { lessonId: string; drafts: Draft[]; baseVersion: string };
const allowed = Object.keys(lessonFileTitles) as DraftType[];
const MAX_CONTENT = 30000;

class ReviewError extends Error {
  constructor(message: string, readonly status: number) { super(message); }
}

function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new ReviewError('请求格式无效', 400);
  }
  return value as Record<string, unknown>;
}

function validTypes(value: unknown): DraftType[] {
  if (!Array.isArray(value) || !value.length || value.length > allowed.length ||
      value.some((type) => !allowed.includes(type as DraftType)) || new Set(value).size !== value.length) {
    throw new ReviewError('请选择有效且不重复的课时文件类型', 400);
  }
  return value as DraftType[];
}

// Optimistic concurrency fingerprint, not an authorization token. Check again
// inside updateServerCourse so edits made during generation are not overwritten.
function version(lesson: CourseLesson, types: DraftType[]) {
  const files = [...types].sort().map((type) => ({
    type,
    files: (lesson.files ?? []).filter((file) => file.type === type),
  }));
  return createHash('sha256').update(JSON.stringify(files)).digest('hex');
}

function failure(error: unknown) {
  return NextResponse.json({ success: false, error: error instanceof Error ? error.message : '课时操作失败' },
    { status: error instanceof ReviewError ? error.status : 500 });
}

export async function POST(request: NextRequest, context: { params: Promise<{ courseId: string }> }) {
  try {
    const { courseId } = await context.params;
    const body = record(await request.json());
    const fileTypes = validTypes(body.fileTypes);
    if (typeof body.lessonId !== 'string' || !body.lessonId) throw new ReviewError('请选择课时', 400);
    if (body.instruction !== undefined && typeof body.instruction !== 'string') throw new ReviewError('教师指令无效', 400);
    const course = await readServerCourse(courseId);
    const lesson = course?.modules.flatMap((module) => module.lessons).find((item) => item.id === body.lessonId);
    if (!course || !lesson) throw new ReviewError('目标课时不存在', 404);
    const baseVersion = version(lesson, fileTypes);
    const generated = await generateLessonFileContent(course, lesson.title, fileTypes,
      typeof body.instruction === 'string' ? body.instruction.slice(0, 4000) : undefined);
    const drafts = fileTypes.map((type) => ({
      type, title: lessonFileTitles[type],
      content: typeof generated?.[type] === 'string' ? generated[type]!.trim() : '',
    }));
    if (drafts.some((draft) => !draft.content || draft.content.length > MAX_CONTENT)) {
      throw new Error('模型未返回完整且长度有效的课时内容，请重试生成');
    }
    // POST never persists: drafts stay in the review page until explicit approval.
    return NextResponse.json({ success: true, lessonId: lesson.id, lessonTitle: lesson.title, baseVersion, drafts });
  } catch (error) { return failure(error); }
}

export async function PATCH(request: NextRequest, context: { params: Promise<{ courseId: string }> }) {
  try {
    const { courseId } = await context.params;
    const body = record(await request.json());
    // Retain the single-lesson shape; batch review uses { lessons: [...] }.
    const rawLessons = body.lessons === undefined ? [body] : body.lessons;
    if (!Array.isArray(rawLessons) || !rawLessons.length || rawLessons.length > 100) {
      throw new ReviewError('审核课时数量无效', 400);
    }
    const lessons: ReviewedLesson[] = rawLessons.map((value) => {
      const item = record(value);
      if (typeof item.lessonId !== 'string' || !item.lessonId ||
          typeof item.baseVersion !== 'string' || !/^[a-f0-9]{64}$/.test(item.baseVersion) ||
          !Array.isArray(item.drafts)) throw new ReviewError('审核内容或版本无效，请重新生成草稿', 400);
      const drafts = item.drafts.map((value) => record(value));
      validTypes(drafts.map((draft) => draft.type));
      if (drafts.some((draft) => typeof draft.content !== 'string' || !draft.content.trim() || draft.content.length > MAX_CONTENT)) {
        throw new ReviewError('审核内容不能为空或超过 30000 字', 400);
      }
      return { lessonId: item.lessonId, baseVersion: item.baseVersion, drafts: drafts as Draft[] };
    });
    if (new Set(lessons.map((lesson) => lesson.lessonId)).size !== lessons.length) {
      throw new ReviewError('审核课时不能重复', 400);
    }
    const now = Date.now();
    const updated = await updateServerCourse(courseId, (course) => {
      const currentLessons = course.modules.flatMap((module) => module.lessons);
      // Validate the entire batch before any mutation or persistence occurs.
      for (const reviewed of lessons) {
        const lesson = currentLessons.find((item) => item.id === reviewed.lessonId);
        if (!lesson) throw new ReviewError('目标课时已不存在，请返回工作台', 409);
        if (version(lesson, reviewed.drafts.map((draft) => draft.type)) !== reviewed.baseVersion) {
          throw new ReviewError(`“${lesson.title}”的原文件已变化，请重新生成草稿后审核`, 409);
        }
      }
      return {
        ...course, updatedAt: now,
        modules: course.modules.map((module) => ({
          ...module,
          lessons: module.lessons.map((lesson) => {
            const reviewed = lessons.find((item) => item.lessonId === lesson.id);
            if (!reviewed) return lesson;
            const files = [...(lesson.files ?? [])];
            for (const draft of reviewed.drafts) {
              const index = files.findIndex((file) => file.type === draft.type);
              const file = {
                ...(index >= 0 ? files[index] : {}),
                id: index >= 0 ? files[index].id : `lesson_file_${now.toString(36)}_${lesson.id}_${draft.type}`,
                lessonId: lesson.id, type: draft.type, title: lessonFileTitles[draft.type],
                content: draft.content.trim(), status: 'ready' as const,
                createdAt: index >= 0 ? files[index].createdAt : now, updatedAt: now,
              };
              if (index >= 0) files[index] = file; else files.push(file);
            }
            return { ...lesson, files, updatedAt: now };
          }),
        })),
      };
    });
    const results = lessons.map((reviewed) => ({
      lessonId: reviewed.lessonId,
      files: updated.modules.flatMap((module) => module.lessons).find((lesson) => lesson.id === reviewed.lessonId)
        ?.files?.filter((file) => reviewed.drafts.some((draft) => draft.type === file.type)) ?? [],
    }));
    return NextResponse.json({ success: true, lessons: results, ...(results.length === 1 ? { files: results[0].files } : {}) });
  } catch (error) { return failure(error); }
}