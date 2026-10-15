import { nanoid } from 'nanoid';
import { readServerCourse, updateServerCourse } from './course-space-storage';
import { generateLessonFileContent } from './teacher-course-operations';

/** Preserve teacher edits on retries and regenerate only missing lesson documents. */
export async function ensureLessonReviewFiles(courseId: string, lessonId: string) {
  const course = await readServerCourse(courseId);
  const lesson = course?.modules
    .flatMap((module) => module.lessons)
    .find((item) => item.id === lessonId);
  if (!course || !lesson) throw new Error('课时不存在');
  const types = ['lesson-objectives', 'knowledge-points'] as const;
  const missing = types.filter(
    (type) => !lesson.files?.some((file) => file.type === type && file.content.trim()),
  );
  if (!missing.length) return;
  const scopedCourse = lesson.materialIds.length
    ? {
        ...course,
        materials: course.materials.filter((material) => lesson.materialIds.includes(material.id)),
      }
    : course;
  const generated = await generateLessonFileContent(
    scopedCourse,
    lesson.title,
    [...missing],
    '生成本次课的课程目标与课程知识点。目标需具体、可评价；知识点按教学顺序包含重点难点，忠于本次材料，供教师逐项审核修改。',
  );
  for (const type of missing) {
    if (typeof generated[type] !== 'string' || !generated[type]?.trim())
      throw new Error('课程目标或知识点生成不完整，请重试');
  }
  await updateServerCourse(courseId, (current) => ({
    ...current,
    updatedAt: Date.now(),
    modules: current.modules.map((module) => ({
      ...module,
      lessons: module.lessons.map((item) => {
        if (item.id !== lessonId) return item;
        const files = [...(item.files ?? [])];
        for (const type of missing) {
          const existing = files.find((file) => file.type === type);
          if (existing?.content.trim()) continue;
          const file = {
            id: existing?.id ?? nanoid(14),
            lessonId,
            type,
            title: type === 'lesson-objectives' ? '课程目标' : '课程知识点',
            content: generated[type]!.trim(),
            status: 'draft' as const,
            createdAt: existing?.createdAt ?? Date.now(),
            updatedAt: Date.now(),
          };
          if (existing) files[files.indexOf(existing)] = file;
          else files.push(file);
        }
        return { ...item, files, updatedAt: Date.now() };
      }),
    })),
  }));
}
