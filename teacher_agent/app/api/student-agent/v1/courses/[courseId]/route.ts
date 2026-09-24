import { type NextRequest } from 'next/server';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import { authorizeStudentAgent } from '@/lib/server/student-agent-auth';
import {
  listCourseArtifacts,
  readPublishedKnowledgePackage,
  readServerCourse,
} from '@/lib/server/course-space-storage';
import { readCourseKnowledgeGraphFromDatabase } from '@/lib/server/course-space-database';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest, context: { params: Promise<{ courseId: string }> }) {
  const denied = authorizeStudentAgent(request);
  if (denied) return denied;
  const { courseId } = await context.params;
  const course = await readServerCourse(courseId);
  if (!course || course.status !== 'active') return apiError('INVALID_REQUEST', 404, '已发布课程不存在');
  const [knowledgePackage, graph, artifacts] = await Promise.all([
    readPublishedKnowledgePackage(courseId),
    readCourseKnowledgeGraphFromDatabase(courseId, { publishedOnly: true }),
    listCourseArtifacts(courseId),
  ]);
  if (!knowledgePackage) return apiError('INVALID_REQUEST', 404, '课程尚未发布知识包');
  const publishedArtifacts = artifacts.filter((artifact) => artifact.status === 'published');
  return apiSuccess({
    schemaVersion: '1.0',
    course: {
      id: course.id,
      title: course.title,
      subject: course.subject,
      gradeBand: course.gradeBand,
      term: course.term,
      description: course.description,
      modules: course.modules.map((module) => ({
        id: module.id,
        title: module.title,
        order: module.order,
        lessons: module.lessons.map((lesson) => ({
          id: lesson.id,
          title: lesson.title,
          order: lesson.order,
          objectives: lesson.objectives,
          files: (lesson.files ?? []).filter((file) => file.status === 'ready'),
        })),
      })),
    },
    knowledgePackage,
    knowledgeGraph: graph,
    artifacts: publishedArtifacts.map((artifact) => ({
      id: artifact.id,
      type: artifact.type,
      title: artifact.title,
      scope: artifact.scope,
      citations: artifact.citations,
      classroomId: artifact.classroomId,
      classroomUrl: artifact.classroomId
        ? `/api/student-agent/v1/courses/${courseId}/classrooms/${artifact.classroomId}`
        : undefined,
      updatedAt: artifact.updatedAt,
    })),
  });
}
