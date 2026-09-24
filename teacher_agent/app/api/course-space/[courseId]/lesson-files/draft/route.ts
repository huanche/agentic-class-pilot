import { NextRequest, NextResponse } from 'next/server';
import type { CourseLessonFileType } from '@/lib/course-space/types';
import { readServerCourse, updateServerCourse } from '@/lib/server/course-space-storage';
import { generateLessonFileContent } from '@/lib/server/teacher-course-operations';

export const runtime = 'nodejs';
export const maxDuration = 180;

const allowed = ['lesson-objectives', 'knowledge-points', 'teaching-activities'] as const;
type DraftType = typeof allowed[number];
const titles: Record<DraftType, string> = {
  'lesson-objectives': '课时目标',
  'knowledge-points': '知识点',
  'teaching-activities': '教学活动',
};

function validTypes(input: unknown): DraftType[] {
  if (!Array.isArray(input)) return [];
  return [...new Set(input.filter((item): item is DraftType => allowed.includes(item as DraftType)))];
}

export async function POST(request: NextRequest, context: { params: Promise<{ courseId: string }> }) {
  const { courseId } = await context.params;
  try {
    const body = await request.json() as { lessonId?: string; fileTypes?: CourseLessonFileType[]; instruction?: string };
    const fileTypes = validTypes(body.fileTypes);
    if (!body.lessonId || !fileTypes.length) return NextResponse.json({ success: false, error: '请选择课时和生成类型' }, { status: 400 });
    const course = await readServerCourse(courseId);
    const lesson = course?.modules.flatMap((module) => module.lessons).find((item) => item.id === body.lessonId);
    if (!course || !lesson) return NextResponse.json({ success: false, error: '目标课时不存在' }, { status: 404 });
    const generated = await generateLessonFileContent(course, lesson.title, fileTypes, body.instruction?.slice(0, 4000));
    const drafts = fileTypes.map((type) => ({ type, title: titles[type], content: generated[type]?.trim() || '' }));
    if (drafts.some((draft) => !draft.content)) throw new Error('模型未返回完整的课时内容，请重试生成');
    return NextResponse.json({ success: true, lessonTitle: lesson.title, drafts });
  } catch (error) {
    return NextResponse.json({ success: false, error: error instanceof Error ? error.message : '生成失败' }, { status: 500 });
  }
}

export async function PATCH(request: NextRequest, context: { params: Promise<{ courseId: string }> }) {
  const { courseId } = await context.params;
  try {
    const body = await request.json() as { lessonId?: string; drafts?: Array<{ type: CourseLessonFileType; content: string }> };
    const fileTypes = validTypes(body.drafts?.map((draft) => draft.type));
    if (!body.lessonId || !fileTypes.length || fileTypes.length !== body.drafts?.length) {
      return NextResponse.json({ success: false, error: '审核内容无效' }, { status: 400 });
    }
    if (body.drafts?.some((draft) => typeof draft.content !== 'string' || !draft.content.trim() || draft.content.length > 30000)) {
      return NextResponse.json({ success: false, error: '审核内容不能为空或超过 30000 字' }, { status: 400 });
    }
    const current = await readServerCourse(courseId);
    if (!current?.modules.some((module) => module.lessons.some((lesson) => lesson.id === body.lessonId))) {
      return NextResponse.json({ success: false, error: '目标课时不存在' }, { status: 404 });
    }
    const now = Date.now();
    const updated = await updateServerCourse(courseId, (course) => ({
      ...course,
      updatedAt: now,
      modules: course.modules.map((module) => ({
        ...module,
        lessons: module.lessons.map((lesson) => {
          if (lesson.id !== body.lessonId) return lesson;
          const files = [...(lesson.files ?? [])];
          for (const draft of body.drafts ?? []) {
            const type = draft.type as DraftType;
            const existing = files.findIndex((file) => file.type === type);
            const file = {
              id: existing >= 0 ? files[existing].id : `lesson_file_${now.toString(36)}_${type}`,
              lessonId: lesson.id,
              type,
              title: titles[type],
              content: draft.content.trim(),
              status: 'ready' as const,
              createdAt: existing >= 0 ? files[existing].createdAt : now,
              updatedAt: now,
            };
            if (existing >= 0) files[existing] = file;
            else files.push(file);
          }
          return { ...lesson, files, updatedAt: now };
        }),
      })),
    }));
    const lesson = updated.modules.flatMap((module) => module.lessons).find((item) => item.id === body.lessonId);
    return NextResponse.json({ success: true, files: lesson?.files?.filter((file) => fileTypes.includes(file.type as DraftType)) ?? [] });
  } catch (error) {
    return NextResponse.json({ success: false, error: error instanceof Error ? error.message : '保存失败' }, { status: 500 });
  }
}
