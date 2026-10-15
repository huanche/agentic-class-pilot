import { type NextRequest } from 'next/server';
import { z } from 'zod';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import {
  deleteCourseArtifact,
  listCourseArtifacts,
  readCourseArtifact,
  readServerCourse,
  saveCourseArtifact,
  updateServerCourse,
} from '@/lib/server/course-space-storage';

const treeActionSchema = z.discriminatedUnion('action', [
  z.object({ action: z.literal('delete-lesson'), lessonId: z.string().min(1) }),
  z.object({ action: z.literal('delete-module'), moduleId: z.string().min(1) }),
  z.object({
    action: z.literal('move-item'),
    itemKind: z.enum(['material', 'course-file', 'artifact']),
    itemId: z.string().min(1),
    targetLessonId: z.string().min(1),
  }),
]);

export async function POST(req: NextRequest, context: { params: Promise<{ courseId: string }> }) {
  const { courseId } = await context.params;
  const parsed = treeActionSchema.safeParse(await req.json().catch(() => null));
  if (!parsed.success) return apiError('INVALID_REQUEST', 400, '目录操作参数无效');
  const body = parsed.data;
  const course = await readServerCourse(courseId);
  if (!course) return apiError('INVALID_REQUEST', 404, '课程不存在');

  const allLessons = course.modules.flatMap((module) => module.lessons);
  const artifacts = body.action === 'move-item' ? [] : await listCourseArtifacts(course.id);

  if (body.action === 'delete-lesson') {
    const lesson = allLessons.find((item) => item.id === body.lessonId);
    if (!lesson) return apiError('INVALID_REQUEST', 404, '课时文件夹不存在');
    const artifactIds = artifacts
      .filter((item) => item.scope.type === 'lesson' && item.scope.lessonId === lesson.id)
      .map((item) => item.id);
    await updateServerCourse(course.id, (current) => ({
      ...current,
      updatedAt: Date.now(),
      modules: current.modules.map((module) => ({
        ...module,
        lessons: module.lessons
          .filter((item) => item.id !== lesson.id)
          .map((item, order) => ({ ...item, order: order + 1 })),
      })),
    }));
    await Promise.all(artifactIds.map((id) => deleteCourseArtifact(id)));
    return apiSuccess({ deleted: 'lesson', artifactCount: artifactIds.length });
  }

  if (body.action === 'delete-module') {
    const courseModule = course.modules.find((item) => item.id === body.moduleId);
    if (!courseModule) return apiError('INVALID_REQUEST', 404, '课程模块不存在');
    const lessonIds = new Set(courseModule.lessons.map((lesson) => lesson.id));
    const artifactIds = artifacts
      .filter(
        (item) =>
          (item.scope.type === 'module' && item.scope.moduleId === courseModule.id) ||
          (item.scope.type === 'lesson' && lessonIds.has(item.scope.lessonId)),
      )
      .map((item) => item.id);
    await updateServerCourse(course.id, (current) => ({
      ...current,
      updatedAt: Date.now(),
      modules: current.modules
        .filter((item) => item.id !== courseModule.id)
        .map((item, order) => ({ ...item, order: order + 1 })),
    }));
    await Promise.all(artifactIds.map((id) => deleteCourseArtifact(id)));
    return apiSuccess({ deleted: 'module', artifactCount: artifactIds.length });
  }

  if (body.action !== 'move-item') return apiError('INVALID_REQUEST', 400, '不支持的目录操作');
  const target = allLessons.find((lesson) => lesson.id === body.targetLessonId);
  if (!target) return apiError('INVALID_REQUEST', 404, '目标课时文件夹不存在');
  const now = Date.now();

  if (body.itemKind === 'artifact') {
    const artifact = await readCourseArtifact(body.itemId);
    if (!artifact || artifact.courseId !== course.id)
      return apiError('INVALID_REQUEST', 404, '教学产物不存在');
    if (artifact.scope.type === 'lesson' && artifact.scope.lessonId === target.id)
      return apiSuccess({ moved: 'artifact', targetLessonId: target.id });
    await saveCourseArtifact({
      ...artifact,
      scope: { type: 'lesson', lessonId: target.id },
      updatedAt: now,
    });
    return apiSuccess({ moved: 'artifact', targetLessonId: target.id });
  }

  if (body.itemKind === 'material') {
    if (!course.materials.some((material) => material.id === body.itemId))
      return apiError('INVALID_REQUEST', 404, '课程材料不存在');
    const locations = allLessons.filter((lesson) => lesson.materialIds.includes(body.itemId));
    if (locations.length === 1 && locations[0].id === target.id)
      return apiSuccess({ moved: 'material', targetLessonId: target.id });
    await updateServerCourse(course.id, (current) => ({
      ...current,
      updatedAt: now,
      modules: current.modules.map((module) => ({
        ...module,
        lessons: module.lessons.map((lesson) => ({
          ...lesson,
          materialIds:
            lesson.id === target.id
              ? [
                  ...new Set([
                    ...lesson.materialIds.filter((id) => id !== body.itemId),
                    body.itemId,
                  ]),
                ]
              : lesson.materialIds.filter((id) => id !== body.itemId),
          updatedAt:
            lesson.materialIds.includes(body.itemId) || lesson.id === target.id
              ? now
              : lesson.updatedAt,
        })),
      })),
    }));
    return apiSuccess({ moved: 'material', targetLessonId: target.id });
  }

  const source = allLessons.find((lesson) =>
    (lesson.files ?? []).some((file) => file.id === body.itemId),
  );
  const file = source?.files?.find((item) => item.id === body.itemId);
  if (!source || !file) return apiError('INVALID_REQUEST', 404, '课程结构文件不存在');
  if (source.id === target.id)
    return apiSuccess({ moved: 'course-file', targetLessonId: target.id });
  if ((target.files ?? []).some((item) => item.type === file.type && item.id !== file.id))
    return apiError('INVALID_REQUEST', 409, '目标课时已包含同类型的课程文件，请选择其他课时');
  await updateServerCourse(course.id, (current) => ({
    ...current,
    updatedAt: now,
    modules: current.modules.map((module) => ({
      ...module,
      lessons: module.lessons.map((lesson) => {
        const without = (lesson.files ?? []).filter((item) => item.id !== file.id);
        if (lesson.id === target.id)
          return {
            ...lesson,
            files: [...without, { ...file, lessonId: target.id, updatedAt: now }],
            updatedAt: now,
          };
        return without.length === (lesson.files ?? []).length
          ? lesson
          : { ...lesson, files: without, updatedAt: now };
      }),
    })),
  }));
  return apiSuccess({ moved: 'course-file', targetLessonId: target.id });
}
