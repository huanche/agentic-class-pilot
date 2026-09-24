import { type NextRequest } from 'next/server';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import { DEFAULT_TEACHER_ID, type CourseKnowledgeGraph } from '@/lib/course-space/types';
import { getKnowledgeGraphStorageMode, readCourseKnowledgeGraph, saveCourseKnowledgeGraph } from '@/lib/server/course-knowledge-store';
import { bootstrapCourseKnowledgeGraph } from '@/lib/server/course-knowledge-graph';
import { readServerCourse } from '@/lib/server/course-space-storage';

export const dynamic = 'force-dynamic';

export async function GET(_request: NextRequest, context: { params: Promise<{ courseId: string }> }) {
  const { courseId } = await context.params;
  const graph = await readCourseKnowledgeGraph(courseId);
  return apiSuccess({ graph: graph ?? null, databaseConfigured:true, storageMode:getKnowledgeGraphStorageMode() });
}

export async function POST(request: NextRequest, context: { params: Promise<{ courseId: string }> }) {
  const { courseId } = await context.params;
  const body = await request.json().catch(() => ({})) as { action?: string; teacherId?: string };
  if (body.action !== 'bootstrap') return apiError('INVALID_REQUEST', 400, '不支持的图谱操作');
  try { return apiSuccess({ graph:await bootstrapCourseKnowledgeGraph(courseId, body.teacherId || DEFAULT_TEACHER_ID) }, 201); }
  catch (error) { return apiError('INVALID_REQUEST', 400, error instanceof Error ? error.message : String(error)); }
}

export async function PUT(request: NextRequest, context: { params: Promise<{ courseId: string }> }) {
  const { courseId } = await context.params;
  const course = await readServerCourse(courseId);
  if (!course) return apiError('INVALID_REQUEST', 404, '课程不存在');
  const graph = await request.json() as CourseKnowledgeGraph;
  if (graph.courseId !== courseId || graph.createdBy !== course.teacherId || graph.status === 'published') {
    return apiError('INVALID_REQUEST', 400, '图谱归属不一致，或不能直接覆盖已发布版本');
  }
  await saveCourseKnowledgeGraph(graph);
  return apiSuccess({ graph });
}
