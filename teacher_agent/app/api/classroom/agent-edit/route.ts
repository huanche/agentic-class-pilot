import type { NextRequest } from 'next/server';
import { apiError } from '@/lib/server/api-response';
import { handleAgentEdit, type AgentEditBody } from '@/lib/server/agent-edit';
import { isValidClassroomId, readClassroom } from '@/lib/server/classroom-storage';
import { readClassroomBindingFromDatabase } from '@/lib/server/course-space-database';
import { readServerCourse } from '@/lib/server/course-space-storage';

export const maxDuration = 300;

export async function POST(req: NextRequest) {
  const id = req.nextUrl.searchParams.get('id');
  if (!id || !isValidClassroomId(id)) return apiError('INVALID_REQUEST', 400, '请指定要修改的课件');

  // Middleware authorizes this classroom query. Also fail closed here when the
  // classroom has no course binding; never turn the legacy agent into an open API.
  if (process.env.PLATFORM_AUTH_ENABLED === 'true') {
    const binding = await readClassroomBindingFromDatabase(id);
    const course = binding?.courseId ? await readServerCourse(binding.courseId) : null;
    if (!course) return apiError('INVALID_REQUEST', 404, '课件所属课程不存在');
    if (
      req.headers.get('x-platform-user-id') !== course.teacherId &&
      req.headers.get('x-platform-admin') !== 'true'
    )
      return apiError('INVALID_REQUEST', 403, '无权修改此课程的课件');
  }

  const classroom = await readClassroom(id);
  if (!classroom) return apiError('INVALID_REQUEST', 404, '课件不存在');
  let body: AgentEditBody & Record<string, unknown>;
  try {
    body = await req.json();
  } catch {
    return apiError('INVALID_REQUEST', 400, '修改请求格式不正确');
  }
  const contexts = body?.sceneContextMap;
  const sceneIds = new Set(classroom.scenes.map((scene) => scene.id));
  if (
    !body?.scene?.id ||
    !contexts ||
    typeof contexts !== 'object' ||
    Array.isArray(contexts) ||
    !Object.hasOwn(contexts, body.scene.id) ||
    Object.entries(contexts).some(
      ([sceneId, context]) => !sceneIds.has(sceneId) || !context || context.stageId !== id,
    )
  )
    return apiError('INVALID_REQUEST', 400, '页面不属于当前课件，请重新打开课件后重试');

  // Keep the teacher's current unsaved canvas content, but restrict every tool's
  // scene context to this authorized classroom. Tools only return client patches.
  return handleAgentEdit(req, body);
}
