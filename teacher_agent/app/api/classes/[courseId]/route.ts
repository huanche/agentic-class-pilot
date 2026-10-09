import { type NextRequest } from 'next/server';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import { platformCourseRoster } from '@/lib/server/platform-course-members';
import {
  fetchStudentLearningSummaries,
  type StudentLearningSummary,
} from '@/lib/server/student-learning-data';
import { listCourseArtifacts, readServerCourse } from '@/lib/server/course-space-storage';
import type { CourseStudentLearningState } from '@/lib/course-space/types';

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
  });
  // Platform enrollment is the roster source of truth; learning state is
  // aggregated live from the student schema on every request — no push
  // mirror, no classStudents fallback (standalone mode keeps the local field).
  const roster = await platformCourseRoster(request as NextRequest, courseId).catch(() => undefined);
  const memberIds = (roster?.members ?? []).map((member) => member.studentId);
  const summaries = roster?.platformCourseId
    ? await fetchStudentLearningSummaries(roster.platformCourseId, memberIds).catch(
        (error: unknown) => {
          console.warn('[classes] 学习数据实时聚合失败，按未开始显示:', error);
          return new Map<string, StudentLearningSummary>();
        },
      )
    : new Map<string, StudentLearningSummary>();
  // 可学课时总数：已发布且带 classroom 的课件数（与平台 progress 的口径一致，
  // 没有课堂的课件学生进不去，不算课时）。
  const totalLessons = artifacts.filter((item) => Boolean(item.classroomUrl)).length;
  const now = Date.now();
  const DAY_MS = 86_400_000;
  const students: CourseStudentLearningState[] = (roster?.members ?? []).map((member) => {
    const summary = summaries.get(member.studentId);
    if (!summary) {
      return {
        studentId: member.studentId,
        name: member.name,
        email: member.email,
        status: 'not-started' as const,
        progress: 0,
        completedResourceIds: [],
        lastActiveAt: member.enrolledAt ? Date.parse(member.enrolledAt) : 0,
      };
    }
    const learnedLessons = Math.min(summary.learnedLessons, Math.max(totalLessons, 0));
    const progress = totalLessons > 0 ? Math.min(100, Math.round((learnedLessons / totalLessons) * 100)) : 0;
    const daysSinceActive = summary.lastActiveAt > 0 ? (now - summary.lastActiveAt) / DAY_MS : Number.POSITIVE_INFINITY;
    const daysSinceEnrolled = member.enrolledAt && Number.isFinite(Date.parse(member.enrolledAt))
      ? (now - Date.parse(member.enrolledAt)) / DAY_MS
      : Number.POSITIVE_INFINITY;
    const status: CourseStudentLearningState['status'] =
      totalLessons > 0 && learnedLessons >= totalLessons
        ? 'completed'
        : (learnedLessons === 0 && daysSinceEnrolled > 7) || daysSinceActive > 7
          ? 'needs-attention'
          : 'learning';
    return {
      studentId: member.studentId,
      name: member.name,
      email: member.email,
      status,
      progress,
      completedResourceIds: [],
      lastActiveAt: summary.lastActiveAt || (member.enrolledAt ? Date.parse(member.enrolledAt) : 0),
      learnedLessons,
      totalLessons,
      sessionCount: summary.sessionCount,
      endedCount: summary.endedCount,
    };
  });
  // 教师先看到需要干预的学生：需要关注 → 学习中 → 未开始 → 已完成，同级按最近活跃。
  const statusOrder = { 'needs-attention': 0, learning: 1, 'not-started': 2, completed: 3 } as const;
  students.sort((a, b) => statusOrder[a.status] - statusOrder[b.status] || (b.lastActiveAt ?? 0) - (a.lastActiveAt ?? 0));
  return apiSuccess({
    students,
  });
}
