import { type NextRequest } from 'next/server';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import { platformCourseMembers } from '@/lib/server/platform-course-members';
import { listCourseArtifacts, readServerCourse } from '@/lib/server/course-space-storage';

export const dynamic = 'force-dynamic';

function withClassReturn(url: string, courseId: string) {
  const separator = url.includes('?') ? '&' : '?';
  return `${url}${separator}from=${encodeURIComponent(`/classes/${courseId}`)}`;
}

export async function GET(request: Request, context: { params: Promise<{ courseId: string }> }) {
  const { courseId } = await context.params;
  const course = await readServerCourse(courseId);
  if (!course || course.status !== 'active') {
    return apiError('INVALID_REQUEST', 404, '正在授课的课程不存在');
  }
  // Artifacts are keyed by the id the course was created under; `courseId` may
  // be the platform UUID, so list under the canonical id.
  const artifacts = (await listCourseArtifacts(course.id)).filter(
    (item) => item.status === 'published' && item.classVisible && item.classPublicationId,
  );
  const materials = course.materials.filter((item) => item.classVisible && item.classPublicationId);
  const lessonFiles = course.modules
    .flatMap((courseModule) => courseModule.lessons)
    .flatMap((lesson) => lesson.files ?? [])
    .filter((item) => item.classVisible && item.classPublicationId);
  const materialLessonIds = new Map<string, string[]>();
  for (const courseModule of course.modules) {
    for (const lesson of courseModule.lessons) {
      for (const materialId of lesson.materialIds) {
        materialLessonIds.set(materialId, [
          ...(materialLessonIds.get(materialId) ?? []),
          lesson.id,
        ]);
      }
    }
  }
  return apiSuccess({
    course: {
      id: course.id,
      title: course.title,
      subject: course.subject,
      gradeBand: course.gradeBand,
      term: course.term,
      description: course.description,
      modules: course.modules.map((courseModule) => ({
        ...courseModule,
        objectives: [],
        lessons: courseModule.lessons.map((lesson) => ({
          ...lesson,
          objectives: [],
          materialIds: [],
          files: [],
        })),
      })),
    },
    resources: [
      ...materials.map((item) => ({
        id: item.id,
        title: item.name,
        origin: 'teacher' as const,
        kind: 'material' as const,
        status: item.status,
        url: withClassReturn(`/api/course-space/${courseId}/materials/${item.id}`, courseId),
        activatedAt: item.activatedAt,
        publicationId: item.classPublicationId,
        publishedAt: item.classPublishedAt,
        scope: materialLessonIds.get(item.id)?.length
          ? { type: 'lessons' as const, lessonIds: materialLessonIds.get(item.id)! }
          : { type: 'course' as const },
      })),
      ...artifacts.map((item) => ({
        id: item.id,
        title: item.title,
        origin: 'agent' as const,
        kind: 'artifact' as const,
        type: item.type,
        status: item.status,
        url: withClassReturn(
          item.classroomUrl || `/course-space/${courseId}/artifacts/${item.id}/view`,
          courseId,
        ),
        activatedAt: item.activatedAt,
        publicationId: item.classPublicationId,
        publishedAt: item.classPublishedAt,
        scope: item.scope,
      })),
      ...lessonFiles.map((item) => ({
        id: item.id,
        title: item.title,
        origin: 'agent' as const,
        kind: 'artifact' as const,
        type: item.type,
        status: item.status,
        url: withClassReturn(`/api/course-space/${courseId}/lesson-files/${item.id}`, courseId),
        activatedAt: item.classPublishedAt,
        publicationId: item.classPublicationId,
        publishedAt: item.classPublishedAt,
        scope: { type: 'lesson' as const, lessonId: item.lessonId },
      })),
    ].sort((a, b) => (b.activatedAt ?? 0) - (a.activatedAt ?? 0)),
    // Platform enrollment is the roster source of truth. The local field only
    // remains as a standalone/demo fallback until student progress is migrated.
    students: (await platformCourseMembers(request as NextRequest, courseId).catch(() => undefined))?.map((member) => {
      // 平台学情同步（PUT students）写入的 classStudents 优先于空白名单状态，
      // 否则授课管理永远显示「未开始 0%」。
      const synced = (course.classStudents ?? []).find((item) => item.studentId === member.studentId);
      return synced ?? {
        studentId: member.studentId,
        name: member.name,
        status: 'not-started' as const,
        progress: 0,
        completedResourceIds: [],
        lastActiveAt: member.enrolledAt ? Date.parse(member.enrolledAt) : 0,
      };
    }) ?? course.classStudents ?? [],
  });
}
