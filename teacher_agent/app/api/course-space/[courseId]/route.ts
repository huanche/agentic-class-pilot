import { type NextRequest } from 'next/server';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import {
  deleteServerCourse,
  CourseDeletionConflict,
  CourseUpdateConflict,
  listCourseArtifacts,
  listCourseJobs,
  readServerCourse,
  saveServerCourse,
} from '@/lib/server/course-space-storage';
import type { CourseSpace } from '@/lib/course-space/types';

export const dynamic = 'force-dynamic';

export async function DELETE(
  _req: NextRequest,
  context: { params: Promise<{ courseId: string }> },
) {
  const { courseId } = await context.params;
  try {
    await deleteServerCourse(courseId);
    return apiSuccess({ deleted: true });
  } catch (error) {
    if (error instanceof CourseDeletionConflict)
      return apiError('INVALID_REQUEST', 409, error.message);
    return apiError('INTERNAL_ERROR', 500, '课程删除失败，请重试');
  }
}

export async function GET(_req: NextRequest, context: { params: Promise<{ courseId: string }> }) {
  const { courseId } = await context.params;
  const course = await readServerCourse(courseId);
  if (!course) return apiError('INVALID_REQUEST', 404, '课程不存在');
  // `courseId` may be a platform UUID while jobs/artifacts are keyed by the id
  // the course was created under; always list under the canonical course id.
  const [jobs, artifacts] = await Promise.all([
    listCourseJobs(course.id),
    listCourseArtifacts(course.id),
  ]);
  return apiSuccess({ course, jobs, artifacts });
}

export async function PUT(req: NextRequest, context: { params: Promise<{ courseId: string }> }) {
  const { courseId } = await context.params;
  const existing = await readServerCourse(courseId);
  if (!existing) return apiError('INVALID_REQUEST', 404, '课程不存在');
  const body = (await req.json()) as CourseSpace;
  if (body.id !== existing.id || body.teacherId !== existing.teacherId) {
    return apiError('INVALID_REQUEST', 400, '课程标识或教师归属不可修改');
  }
  const archivedMaterialIds = new Set(existing.archivedMaterials?.map((item) => item.id));
  if (
    archivedMaterialIds.size > 0 &&
    (body.materials.some((item) => archivedMaterialIds.has(item.id)) ||
      body.modules.some((module) =>
        module.lessons?.some((lesson) =>
          lesson.materialIds?.some((id) => archivedMaterialIds.has(id)),
        ),
      ))
  )
    return apiError('INVALID_REQUEST', 409, '源文件已替换，请刷新课程后重试目录编辑');
  // Structure edits arrive as a full course object that may be a stale copy
  // (long-lived workspace tab). Publication state and the platform-synced
  // roster are server-owned: a stale save must never flip a published course
  // back to draft or drop the active knowledge package link.
  // Structural saves cannot publish files or overwrite released lesson content.
  const existingFiles = new Map(
    existing.modules
      .flatMap((m) => m.lessons ?? [])
      .flatMap((l) => l.files ?? [])
      .map((f) => [f.id, f]),
  );
  const publications = await listCourseArtifacts(existing.id);
  const protectedLessonIds = new Set([
    ...publications
      .filter((item) => item.classPublicationId)
      .flatMap((item) =>
        item.publicationPlacement?.lessonId
          ? [item.publicationPlacement.lessonId]
          : item.scope.type === 'lesson'
            ? [item.scope.lessonId]
            : [],
      ),
    ...existing.materials
      .filter((item) => item.classPublicationId && item.publicationPlacement)
      .map((item) => item.publicationPlacement!.lessonId),
  ]);
  const submittedLessons = body.modules.flatMap((module) => module.lessons ?? []);
  for (const lesson of existing.modules.flatMap((module) => module.lessons)) {
    if (
      protectedLessonIds.has(lesson.id) &&
      !submittedLessons.some((item) => item.id === lesson.id)
    )
      return apiError('INVALID_REQUEST', 409, '已确认发布归属的课时不能删除');
    for (const file of lesson.files ?? [])
      if (
        file.classPublicationId &&
        !submittedLessons.some(
          (item) => item.id === lesson.id && item.files?.some((f) => f.id === file.id),
        )
      )
        return apiError('INVALID_REQUEST', 409, '已发布文件不能通过目录编辑删除或更改课时');
  }
  for (const material of existing.materials)
    if (material.classPublicationId && !body.materials.some((item) => item.id === material.id))
      return apiError('INVALID_REQUEST', 409, '不能通过目录编辑删除已发布资料');
  const materials = body.materials.map((item) => {
    const saved = existing.materials.find((m) => m.id === item.id);
    return {
      ...item,
      purpose: saved?.purpose ?? 'course-material',
      publicationPlacement: saved?.publicationPlacement,
      classVisible: saved?.classVisible ?? false,
      classPublicationId: saved?.classPublicationId,
      classPublishedAt: saved?.classPublishedAt,
      activatedAt: saved?.activatedAt,
    };
  });
  const modules = body.modules.map((module) => ({
    ...module,
    ...(module.lessons
      ? {
          lessons: module.lessons.map((lesson) => ({
            ...lesson,
            ...(() => {
              const saved = existing.modules
                .flatMap((m) => m.lessons)
                .find((item) => item.id === lesson.id);
              return saved?.week
                ? {
                    week: saved.week,
                    lessonNumber: saved.lessonNumber,
                    teachingHours: saved.teachingHours,
                  }
                : {};
            })(),
            files: lesson.files?.map((file) => {
              const saved = existingFiles.get(file.id);
              return saved?.classPublicationId
                ? saved
                : {
                    ...file,
                    publicationPlacement: undefined,
                    classVisible: false,
                    classPublicationId: undefined,
                    classPublishedAt: undefined,
                  };
            }),
          })),
        }
      : {}),
  }));
  const merged: CourseSpace = {
    ...body,
    onboarding: existing.onboarding,
    materials,
    archivedMaterials: existing.archivedMaterials,
    modules,
    activeKnowledgeGraphVersion: existing.activeKnowledgeGraphVersion,
    status: existing.status,
    activeKnowledgePackageId: existing.activeKnowledgePackageId,
    classStudents: existing.classStudents,
  };
  try {
    return apiSuccess({ course: await saveServerCourse(merged, existing) });
  } catch (error) {
    if (error instanceof CourseUpdateConflict)
      return apiError('INVALID_REQUEST', 409, error.message);
    throw error;
  }
}
