import type { NextRequest } from 'next/server';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import { DEFAULT_TEACHER_ID } from '@/lib/course-space/types';
import { listServerCourses } from '@/lib/server/course-space-storage';
import { resolveTeacherId } from '@/lib/server/platform-course-bridge';
import { platformCourseMembers } from '@/lib/server/platform-course-members';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const teacherId = resolveTeacherId(request, DEFAULT_TEACHER_ID);
  if (!teacherId) {
    return apiError('INVALID_CREDENTIALS', 401, '无法确认教师身份');
  }
  const courses = (await listServerCourses(teacherId))
    .filter((course) => course.status === 'active')
    .map(async (course) => {
      // Roster availability must never hide an already-published course.
      // The next request retries the platform projection after a platform restart.
      const members = await platformCourseMembers(request, course.id).catch(() => undefined);
      return {
      id: course.id,
      title: course.title,
      subject: course.subject,
      gradeBand: course.gradeBand,
      term: course.term,
      description: course.description,
      moduleCount: course.modules.length,
      lessonCount: course.modules.reduce((count, item) => count + item.lessons.length, 0),
      studentCount: members?.length ?? course.classStudents?.length ?? 0,
      updatedAt: course.updatedAt,
      };
    });
  return apiSuccess({ courses: await Promise.all(courses) });
}
