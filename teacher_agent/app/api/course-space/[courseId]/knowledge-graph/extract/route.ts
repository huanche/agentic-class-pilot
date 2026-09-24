import { after, type NextRequest } from 'next/server';
import { nanoid } from 'nanoid';
import { DEFAULT_TEACHER_ID, type CourseKnowledgeExtractionJob } from '@/lib/course-space/types';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import { getKnowledgeGraphStorageMode, listCourseKnowledgeExtractionJobs, readCourseKnowledgeGraph,
  saveCourseKnowledgeExtractionJob } from '@/lib/server/course-knowledge-store';
import { runCourseKnowledgeExtractionJob } from '@/lib/server/course-knowledge-extraction';
import { bootstrapCourseKnowledgeGraph } from '@/lib/server/course-knowledge-graph';
import { readServerCourse } from '@/lib/server/course-space-storage';

export const dynamic = 'force-dynamic';
export const maxDuration = 30;

export async function GET(_request: NextRequest, context: { params: Promise<{ courseId: string }> }) {
  const { courseId } = await context.params;
  const jobs = await listCourseKnowledgeExtractionJobs(courseId);
  return apiSuccess({ jobs:jobs ?? [], databaseConfigured:true, storageMode:getKnowledgeGraphStorageMode() });
}

export async function POST(request: NextRequest, context: { params: Promise<{ courseId: string }> }) {
  const { courseId } = await context.params;
  const course = await readServerCourse(courseId);
  if (!course) return apiError('INVALID_REQUEST', 404, '课程不存在');
  const body = await request.json().catch(() => ({})) as { teacherId?: string };
  const teacherId = body.teacherId || DEFAULT_TEACHER_ID;
  if (teacherId !== course.teacherId) return apiError('INVALID_REQUEST', 403, '无权修改该课程');
  let graph = await readCourseKnowledgeGraph(courseId);
  if (graph?.status === 'published') graph = await bootstrapCourseKnowledgeGraph(courseId, teacherId);
  if (!graph) return apiError('INVALID_REQUEST', 409, '请先建立一个未发布的图谱骨架');
  if (!course.materials.some((item) => item.status === 'ready')) {
    return apiError('INVALID_REQUEST', 409, '请先解析至少一份课程材料');
  }
  const running = (await listCourseKnowledgeExtractionJobs(courseId) ?? []).find((job) =>
    job.graphVersion === graph.version && (job.status === 'queued' || job.status === 'running'));
  if (running) return apiSuccess({ job:running }, 202);
  const now = Date.now();
  const id = nanoid(14);
  const job: CourseKnowledgeExtractionJob = {
    id, teacherId, courseId, graphVersion:graph.version, sessionId:`knowledge-${id}`,
    status:'queued', phase:'queued', progress:0, message:'等待知识抽取', createdAt:now, updatedAt:now,
  };
  await saveCourseKnowledgeExtractionJob(job);
  after(() => runCourseKnowledgeExtractionJob(job.id).then(() => undefined));
  return apiSuccess({ job }, 202);
}
