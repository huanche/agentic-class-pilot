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
  // Structure edits arrive as a full course object that may be a stale copy
  // (long-lived workspace tab). Publication state and the platform-synced
  // roster are server-owned: a stale save must never flip a published course
  // back to draft or drop the active knowledge package link.
  const merged: CourseSpace = {
    ...body,
    status: existing.status,
    activeKnowledgePackageId: existing.activeKnowledgePackageId,
    classStudents: existing.classStudents,
  };
  return apiSuccess({ course: await saveServerCourse(merged) });
}
