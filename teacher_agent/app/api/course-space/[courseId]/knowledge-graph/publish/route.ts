import { type NextRequest } from 'next/server';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import { publishCourseKnowledgeGraph } from '@/lib/server/course-knowledge-graph';

export async function POST(request: NextRequest, context: { params: Promise<{ courseId: string }> }) {
  const { courseId } = await context.params;
  const body = await request.json().catch(() => ({})) as { version?: number };
  if (!Number.isInteger(body.version)) return apiError('INVALID_REQUEST', 400, '缺少有效图谱版本');
  try {
    const graph = await publishCourseKnowledgeGraph(courseId, body.version!);
    return graph ? apiSuccess({ graph }) : apiError('INVALID_REQUEST', 404, '图谱版本不存在');
  } catch (error) { return apiError('INVALID_REQUEST', 409, error instanceof Error ? error.message : String(error)); }
}
