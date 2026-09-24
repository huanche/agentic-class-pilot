import { type NextRequest } from 'next/server';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import { readCourseKnowledgeGraphFromDatabase } from '@/lib/server/course-space-database';

/** Student-agent-safe endpoint: draft and review graph versions never leave the teacher domain. */
export async function GET(request: NextRequest, context: { params: Promise<{ courseId: string }> }) {
  const { courseId } = await context.params;
  const graph = await readCourseKnowledgeGraphFromDatabase(courseId, { publishedOnly:true });
  if (!graph) return apiError('INVALID_REQUEST', 404, '该课程尚未发布知识图谱');
  const nodeType = request.nextUrl.searchParams.get('nodeType');
  const lessonId = request.nextUrl.searchParams.get('lessonId');
  const nodes = graph.nodes.filter((node) => (!nodeType || node.type === nodeType) && (!lessonId || node.lessonId === lessonId));
  const nodeIds = new Set(nodes.map((node) => node.id));
  return apiSuccess({ apiVersion:'v1', graph:{ ...graph, nodes, edges:graph.edges.filter((edge) => nodeIds.has(edge.sourceNodeId) || nodeIds.has(edge.targetNodeId)) } });
}
