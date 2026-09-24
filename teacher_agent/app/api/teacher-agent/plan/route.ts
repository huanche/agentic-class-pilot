import { type NextRequest } from 'next/server';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import { planTeacherWorkspaceOperation } from '@/lib/course-space/teacher-agent-intent';
import type { CourseArtifactJob } from '@/lib/course-space/types';
import { readServerCourse } from '@/lib/server/course-space-storage';

export const runtime = 'nodejs';

export async function POST(request: NextRequest) {
  const body = await request.json() as {
    courseId?: string;
    message?: string;
    scope?: CourseArtifactJob['scope'];
  };
  const courseId = body.courseId?.trim();
  const message = body.message?.trim();
  if (!courseId || !message) return apiError('MISSING_REQUIRED_FIELD', 400, '缺少 courseId 或 message');
  if (message.length > 12000) return apiError('INVALID_REQUEST', 400, '教师命令过长');
  const course = await readServerCourse(courseId);
  if (!course) return apiError('INVALID_REQUEST', 404, '课程不存在');
  const plan = planTeacherWorkspaceOperation(message, course, body.scope);
  if (!plan) return apiError('INVALID_REQUEST', 422, '命令未匹配可执行的教师端操作');
  return apiSuccess({ plan });
}
