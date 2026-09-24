import { type NextRequest } from 'next/server';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import {
  deleteCourseArtifact,
  listCourseArtifacts,
  readCourseArtifact,
  readServerCourse,
  saveCourseArtifact,
  updateServerCourse,
} from '@/lib/server/course-space-storage';

type TreeAction =
  | { action: 'delete-lesson'; lessonId: string }
  | { action: 'delete-module'; moduleId: string }
  | {
      action: 'move-item';
      itemKind: 'material' | 'course-file' | 'artifact';
      itemId: string;
      targetLessonId: string;
    };

export async function POST(
  req: NextRequest,
  context: { params: Promise<{ courseId: string }> },
) {
  const { courseId } = await context.params;
  const body = (await req.json()) as TreeAction;
  const course = await readServerCourse(courseId);
  if (!course) return apiError('INVALID_REQUEST', 404, '课程不存在');

  const allLessons = course.modules.flatMap((module) => module.lessons);
  const artifacts = await listCourseArtifacts(courseId);

  if (body.action === 'delete-lesson') {
    const lesson = allLessons.find((item) => item.id === body.lessonId);
    if (!lesson) return apiError('INVALID_REQUEST', 404, '课时文件夹不存在');
    const artifactIds = artifacts
      .filter((item) => item.scope.type === 'lesson' && item.scope.lessonId === lesson.id)
      .map((item) => item.id);
    await updateServerCourse(courseId, (current) => ({
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
    await updateServerCourse(courseId, (current) => ({
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
    if (!artifact || artifact.courseId !== courseId)
      return apiError('INVALID_REQUEST', 404, '教学产物不存在');
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
    await updateServerCourse(courseId, (current) => ({
      ...current,
      updatedAt: now,
      modules: current.modules.map((module) => ({
        ...module,
        lessons: module.lessons.map((lesson) => ({
          ...lesson,
          materialIds:
            lesson.id === target.id
              ? [...new Set([...lesson.materialIds.filter((id) => id !== body.itemId), body.itemId])]
              : lesson.materialIds.filter((id) => id !== body.itemId),
          updatedAt: lesson.materialIds.includes(body.itemId) || lesson.id === target.id
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
  if ((target.files ?? []).some((item) => item.type === file.type && item.id !== file.id))
    return apiError('INVALID_REQUEST', 409, `目标文件夹已包含“${file.title}”`);
  await updateServerCourse(courseId, (current) => ({
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
