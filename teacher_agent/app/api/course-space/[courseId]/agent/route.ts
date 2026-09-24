import { NextRequest, NextResponse } from 'next/server';
import { runTeacherWorkspaceAgent } from '@/lib/server/teacher-workspace-agent';
import {
  planTeacherWorkspaceOperation,
  type TeacherOperationPlan,
} from '@/lib/course-space/teacher-agent-intent';
import { readServerCourse } from '@/lib/server/course-space-storage';
import { executeReadOnlyTeacherPlan } from '@/lib/server/teacher-course-operations';
import type { CourseArtifactJob } from '@/lib/course-space/types';
import {
  getCourseSpaceStorageAdapter,
  type TeacherAgentTurnLease,
} from '@/lib/server/course-space-storage-adapter';

export const runtime = 'nodejs';
export const maxDuration = 180;

const storage = getCourseSpaceStorageAdapter();

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ courseId: string }> },
) {
  const { courseId } = await context.params;
  if (request.nextUrl.searchParams.get('list') === '1') {
    const course = await readServerCourse(courseId);
    if (!course)
      return NextResponse.json({ success: false, error: '课程不存在' }, { status: 404 });
    const sessions = await storage.listTeacherSessions(courseId, course.teacherId);
    const summaries = await Promise.all(
      sessions.slice(0, 40).map(async (session) => {
        const events = await storage.readTeacherEvents(session.id);
        const firstMessage = events.find((event) => event.type === 'user_message');
        const data = firstMessage?.data && typeof firstMessage.data === 'object'
          ? firstMessage.data as Record<string, unknown>
          : {};
        return {
          id: session.id,
          title: typeof data.text === 'string' ? data.text.slice(0, 32) : '新备课会话',
          updatedAt: session.updatedAt,
          status: session.status,
        };
      }),
    );
    return NextResponse.json({ success: true, sessions: summaries });
  }
  const sessionId = request.nextUrl.searchParams.get('sessionId')?.trim();
  if (!sessionId)
    return NextResponse.json({ success: false, error: '缺少 sessionId' }, { status: 400 });
  const session = await storage.getTeacherSession(sessionId);
  if (!session)
    return NextResponse.json({ success: true, session: null, events: [], messages: [] });
  if (session.stageId !== courseId) {
    return NextResponse.json({ success: false, error: '会话不属于当前课程' }, { status: 403 });
  }
  const events = await storage.readTeacherEvents(sessionId);
  const messages: Array<{
    role: 'user' | 'assistant';
    content: string;
    eventId: number;
    plan?: TeacherOperationPlan;
  }> = [];
  for (const event of events) {
    const data =
      event.data && typeof event.data === 'object' ? (event.data as Record<string, unknown>) : {};
    if (event.type === 'user_message' && typeof data.text === 'string') {
      messages.push({ role: 'user', content: data.text, eventId: event.id });
    }
    if (event.type === 'message_end' && typeof data.text === 'string') {
      messages.push({
        role: 'assistant',
        content: data.text,
        eventId: event.id,
        plan: data.plan as TeacherOperationPlan | undefined,
      });
    }
  }
  return NextResponse.json({ success: true, session, events, messages });
}

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ courseId: string }> },
) {
  let lease: TeacherAgentTurnLease | undefined;
  try {
    const { courseId } = await context.params;
    const body = (await request.json()) as {
      sessionId?: string;
      message?: string;
      history?: Array<{ role: 'user' | 'assistant'; content: string }>;
      attachments?: Array<{ name: string; mimeType: string; dataUrl: string }>;
      scope?: CourseArtifactJob['scope'];
      deepInteraction?: boolean;
    };
    if (!body.message?.trim())
      return NextResponse.json({ success: false, error: '请输入问题' }, { status: 400 });
    const course = await readServerCourse(courseId);
    if (!course) return NextResponse.json({ success: false, error: '课程不存在' }, { status: 404 });
    const requestedScope = body.scope;
    if (requestedScope) {
      const scopeExists = requestedScope.type === 'course'
        || (requestedScope.type === 'module' && course.modules.some((item) => item.id === requestedScope.moduleId))
        || (requestedScope.type === 'lesson' && course.modules.some((item) => item.lessons.some((lesson) => lesson.id === requestedScope.lessonId)));
      if (!scopeExists) return NextResponse.json({ success: false, error: '当前工作文件夹已不存在，请重新选择' }, { status: 409 });
    }
    const sessionId = body.sessionId || `teacher-${courseId}-default`;
    lease = await storage.beginTeacherTurn({
      sessionId,
      teacherId: course.teacherId,
      courseId,
      message: body.message.trim(),
    });
    let plan = planTeacherWorkspaceOperation(body.message, course, body.scope);
    if (plan) {
      if (!plan.requiresConfirmation) plan = await executeReadOnlyTeacherPlan(courseId, plan);
      const text = plan.requiresConfirmation
        ? '已形成结构化操作计划，请确认后执行。'
        : plan.result || '课程操作检查已完成。';
      await storage.completeTeacherTurn(lease, { text, mode: 'course-operator', plan });
      return NextResponse.json({
        success: true,
        mode: 'course-operator',
        plan,
        text,
      });
    }
    const attachments = (body.attachments ?? []).slice(0, 3);
    if (attachments.some((item) => !/^image\/(?:png|jpeg|webp)$/u.test(item.mimeType))) {
      return NextResponse.json(
        { success: false, error: '仅支持 PNG、JPEG、WebP 截图' },
        { status: 400 },
      );
    }
    const result = await runTeacherWorkspaceAgent({
      courseId,
      sessionId,
      message: body.message.trim(),
      history: body.history,
      attachments,
      scope: body.scope,
      deepInteraction: body.deepInteraction === true,
    });
    await storage.completeTeacherTurn(lease, result);
    return NextResponse.json({ success: true, ...result });
  } catch (error) {
    await storage.failTeacherTurn(lease, error);
    return NextResponse.json(
      { success: false, error: error instanceof Error ? error.message : String(error) },
      { status: 500 },
    );
  }
}
