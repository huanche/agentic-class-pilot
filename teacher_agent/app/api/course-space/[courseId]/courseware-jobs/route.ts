import { after, type NextRequest } from 'next/server';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import { readServerCourse } from '@/lib/server/course-space-storage';
import { buildRequestOrigin } from '@/lib/server/classroom-storage';
import {
  createBackgroundCoursewareJob,
  runBackgroundCoursewareJob,
} from '@/lib/server/background-courseware';
import type { BackgroundCoursewareInput } from '@/lib/generation/background-courseware';
import type { CourseArtifactJob } from '@/lib/course-space/types';

export const runtime = 'nodejs';
export const maxDuration = 300;

export async function POST(req: NextRequest, context: { params: Promise<{ courseId: string }> }) {
  const { courseId } = await context.params;
  const course = await readServerCourse(courseId);
  if (!course) return apiError('INVALID_REQUEST', 404, '课程不存在');
  if (
    process.env.PLATFORM_AUTH_ENABLED === 'true' &&
    req.headers.get('x-platform-user-id') !== course.teacherId &&
    req.headers.get('x-platform-admin') !== 'true'
  )
    return apiError('INVALID_REQUEST', 403, '无权为此课程创建任务');
  try {
    const { input, scope = { type: 'course' } } = (await req.json()) as {
      input: BackgroundCoursewareInput;
      scope?: CourseArtifactJob['scope'];
    };
    if (
      !input?.stage?.id ||
      !input.sessionId ||
      !Array.isArray(input.outlines) ||
      !input.requirements ||
      !Array.isArray(input.agents)
    )
      return apiError('INVALID_REQUEST', 400, '生成参数不完整，请重新确认大纲');
    const exists =
      scope.type === 'course' ||
      (scope.type === 'module' && course.modules.some((item) => item.id === scope.moduleId)) ||
      (scope.type === 'lesson' &&
        course.modules.some((item) => item.lessons.some((lesson) => lesson.id === scope.lessonId)));
    if (!exists) return apiError('INVALID_REQUEST', 400, '生成范围不属于当前课程');
    const job = await createBackgroundCoursewareJob(input, {
      courseId: course.id,
      teacherId: course.teacherId,
      scope,
      baseUrl: buildRequestOrigin(req),
    });
    // Only model-selection headers enter the in-memory worker. Cookies, auth
    // headers and provider credentials are never persisted in the job payload.
    const headers: Record<string, string> = {};
    for (const name of ['x-model', 'x-api-key', 'x-base-url', 'x-provider-type', 'x-user-locale']) {
      const value = req.headers.get(name);
      if (value) headers[name] = value;
    }
    if (job.status === 'queued' || job.status === 'running')
      after(() => runBackgroundCoursewareJob(job.id, headers));
    return apiSuccess({ job, url: `/course-space/${course.id}/jobs/${job.id}` }, 202);
  } catch (error) {
    return apiError(
      'INVALID_REQUEST',
      400,
      error instanceof Error ? error.message : '创建后台任务失败',
    );
  }
}
