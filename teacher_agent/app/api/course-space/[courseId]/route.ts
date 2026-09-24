import { type NextRequest } from 'next/server';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import {
  listCourseArtifacts,
  listCourseJobs,
  readServerCourse,
  saveServerCourse,
} from '@/lib/server/course-space-storage';
import type { CourseSpace } from '@/lib/course-space/types';

export const dynamic = 'force-dynamic';

export async function GET(_req: NextRequest, context: { params: Promise<{ courseId: string }> }) {
  const { courseId } = await context.params;
  const course = await readServerCourse(courseId);
  if (!course) return apiError('INVALID_REQUEST', 404, '课程不存在');
  const [jobs, artifacts] = await Promise.all([
    listCourseJobs(courseId),
    listCourseArtifacts(courseId),
  ]);
  return apiSuccess({ course, jobs, artifacts });
}

export async function PUT(req: NextRequest, context: { params: Promise<{ courseId: string }> }) {
  const { courseId } = await context.params;
  const existing = await readServerCourse(courseId);
  if (!existing) return apiError('INVALID_REQUEST', 404, '课程不存在');
  const body = (await req.json()) as CourseSpace;
  if (body.id !== courseId || body.teacherId !== existing.teacherId) {
    return apiError('INVALID_REQUEST', 400, '课程标识或教师归属不可修改');
  }
  return apiSuccess({ course: await saveServerCourse(body) });
}
