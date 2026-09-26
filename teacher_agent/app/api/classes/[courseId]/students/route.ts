import { apiError, apiSuccess } from '@/lib/server/api-response';
import type { CourseStudentLearningState } from '@/lib/course-space/types';
import { readServerCourse, updateServerCourse } from '@/lib/server/course-space-storage';

export const dynamic = 'force-dynamic';

const VALID_STATUSES = new Set<CourseStudentLearningState['status']>([
  'not-started',
  'learning',
  'completed',
  'needs-attention',
]);

function optionalInt(value: unknown): number | undefined {
  const n = Number(value);
  return Number.isFinite(n) && n >= 0 ? Math.round(n) : undefined;
}

function normalizeStudent(input: unknown): CourseStudentLearningState | null {
  if (!input || typeof input !== 'object') return null;
  const body = input as Partial<CourseStudentLearningState>;
  if (
    !body.studentId?.trim() ||
    !body.name?.trim() ||
    !body.status ||
    !VALID_STATUSES.has(body.status)
  ) {
    return null;
  }
  const progress = Number(body.progress);
  return {
    studentId: body.studentId.trim(),
    name: body.name.trim(),
    studentNumber: body.studentNumber?.trim() || undefined,
    className: body.className?.trim() || undefined,
    status: body.status,
    progress: Number.isFinite(progress) ? Math.min(100, Math.max(0, Math.round(progress))) : 0,
    completedResourceIds: Array.isArray(body.completedResourceIds)
      ? [
          ...new Set(
            body.completedResourceIds.filter(
              (item): item is string => typeof item === 'string' && item.length > 0,
            ),
          ),
        ]
      : [],
    lastActiveAt: typeof body.lastActiveAt === 'number' ? body.lastActiveAt : Date.now(),
    learnedLessons: optionalInt(body.learnedLessons),
    totalLessons: optionalInt(body.totalLessons),
    sessionCount: optionalInt(body.sessionCount),
    endedCount: optionalInt(body.endedCount),
    stars: optionalInt(body.stars),
  };
}

export async function PUT(request: Request, context: { params: Promise<{ courseId: string }> }) {
  const { courseId } = await context.params;
  const course = await readServerCourse(courseId);
  if (!course || course.status !== 'active') {
    return apiError('INVALID_REQUEST', 404, '正在授课的课程不存在');
  }

  const student = normalizeStudent(await request.json().catch(() => null));
  if (!student) {
    return apiError('INVALID_REQUEST', 400, '学生状态数据不完整');
  }

  const updated = await updateServerCourse(courseId, (current) => {
    const students = current.classStudents ?? [];
    const existingIndex = students.findIndex((item) => item.studentId === student.studentId);
    return {
      ...current,
      classStudents:
        existingIndex < 0
          ? [...students, student]
          : students.map((item, index) => (index === existingIndex ? student : item)),
    };
  });

  return apiSuccess({
    student,
    studentCount: updated.classStudents?.length ?? 0,
  });
}
