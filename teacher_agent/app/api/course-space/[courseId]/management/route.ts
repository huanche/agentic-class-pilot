import { type NextRequest } from 'next/server';
import { z } from 'zod';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import {
  readServerCourse,
  updateServerCourse,
  updateCourseArtifact,
} from '@/lib/server/course-space-storage';

const schema = z
  .object({
    kind: z.enum(['artifacts', 'materials', 'lesson-files', 'modules', 'lessons']),
    id: z.string().min(1),
    title: z
      .string()
      .trim()
      .min(1)
      .max(180)
      .regex(/^[^\u0000-\u001f\u007f]+$/)
      .optional(),
    pinned: z.boolean().optional(),
  })
  .strict()
  .refine((value) => value.title !== undefined || value.pinned !== undefined);

/** Metadata changes preserve identity, content, review and publication bindings. */
export async function PATCH(
  request: NextRequest,
  context: { params: Promise<{ courseId: string }> },
) {
  const parsed = schema.safeParse(await request.json().catch(() => null));
  if (!parsed.success)
    return apiError('INVALID_REQUEST', 400, '名称须为 1–180 个字符，置顶状态须为布尔值');
  const { courseId } = await context.params;
  const course = await readServerCourse(courseId);
  if (!course) return apiError('INVALID_REQUEST', 404, '课程不存在');
  const { kind, id, title, pinned } = parsed.data;
  const patch = {
    ...(title !== undefined ? { title } : {}),
    ...(pinned !== undefined ? { pinned } : {}),
    updatedAt: Date.now(),
  };
  if (kind === 'artifacts') {
    const item = await updateCourseArtifact(id, (artifact) =>
      artifact.courseId !== course.id
        ? null
        : {
            ...artifact,
            ...patch,
            ...(title !== undefined && artifact.wordStorageKey
              ? {
                  wordFileName: `${title.replace(/[\\/:*?"<>|]/g, '_').replace(/\.docx$/i, '')}.docx`,
                }
              : {}),
          },
    );
    if (!item) return apiError('INVALID_REQUEST', 404, '文件不存在');
    return apiSuccess({ item });
  }
  const lessons = course.modules.flatMap((module) => module.lessons);
  const exists =
    kind === 'materials'
      ? course.materials.some((item) => item.id === id)
      : kind === 'modules'
        ? course.modules.some((item) => item.id === id)
        : kind === 'lessons'
          ? lessons.some((item) => item.id === id)
          : lessons.some((lesson) => lesson.files?.some((item) => item.id === id));
  if (!exists) return apiError('INVALID_REQUEST', 404, '文件或文件夹不存在');
  let materialName = title;
  if (kind === 'materials' && title !== undefined) {
    const original = course.materials.find((item) => item.id === id)!;
    const extension = original.name.match(/\.[a-zA-Z0-9]{1,12}$/)?.[0] ?? '';
    materialName = title.toLowerCase().endsWith(extension.toLowerCase())
      ? title
      : `${title}${extension}`;
    if (materialName.length > 180 || /[\\/]/.test(materialName))
      return apiError(
        'INVALID_REQUEST',
        400,
        '文件名不能包含路径分隔符，含扩展名不超过 180 个字符',
      );
  }
  await updateServerCourse(course.id, (current) => ({
    ...current,
    updatedAt: Date.now(),
    materials:
      kind === 'materials'
        ? current.materials.map((item) =>
            item.id === id
              ? {
                  ...item,
                  ...(materialName !== undefined ? { name: materialName } : {}),
                  ...(pinned !== undefined ? { pinned } : {}),
                  updatedAt: patch.updatedAt,
                }
              : item,
          )
        : current.materials,
    modules: current.modules.map((module) => ({
      ...module,
      ...(kind === 'modules' && module.id === id ? patch : {}),
      lessons: module.lessons.map((lesson) => ({
        ...lesson,
        ...(kind === 'lessons' && lesson.id === id ? patch : {}),
        files:
          kind === 'lesson-files'
            ? lesson.files?.map((item) => (item.id === id ? { ...item, ...patch } : item))
            : lesson.files,
      })),
    })),
  }));
  return apiSuccess({ updated: id });
}
