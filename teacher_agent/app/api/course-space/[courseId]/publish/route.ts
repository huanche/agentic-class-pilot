import { type NextRequest } from 'next/server';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import { readServerCourse } from '@/lib/server/course-space-storage';
import { publishCourseChannel } from '@/lib/server/course-channel-publication';

/** Retain the legacy endpoint; the teacher UI initializes this during file publication. */
export async function POST(_req: NextRequest, context: { params: Promise<{ courseId: string }> }) {
  const { courseId } = await context.params;
  const course = await readServerCourse(courseId);
  if (!course) return apiError('INVALID_REQUEST', 404, '课程不存在');
  if (course.status === 'archived') return apiError('INVALID_REQUEST', 409, '归档课程不能发布');
  return apiSuccess({ knowledgePackage: await publishCourseChannel(course) }, 201);
}
