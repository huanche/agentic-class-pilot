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

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ courseId: string }> },
) {
  const denied = authorizeStudentAgent(request);
  if (denied) return denied;
  const { courseId } = await context.params;
  const course = await readServerCourse(courseId);
  if (!course || course.status !== 'active')
    return apiError('INVALID_REQUEST', 404, '已发布课程不存在');
  const [knowledgePackage, graph, artifacts] = await Promise.all([
    readPublishedKnowledgePackage(course.id),
    readCourseKnowledgeGraphFromDatabase(course.id, { publishedOnly: true }),
    listCourseArtifacts(course.id),
  ]);
  if (!knowledgePackage) return apiError('INVALID_REQUEST', 404, '课程尚未发布知识包');
  const publishedArtifacts = artifacts.filter(
    (artifact) =>
      artifact.status === 'published' && artifact.classVisible && artifact.classPublicationId,
  );
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
          files: (lesson.files ?? []).filter(
            (file) => file.status === 'ready' && file.classVisible && file.classPublicationId,
          ),
        })),
      })),
    },
    // Package snapshots predate individual withdrawals. Resolve entries from
    // current publications so revoked content cannot leak through an old package.
    knowledgePackage: {
      ...knowledgePackage,
      entries: publishedArtifacts.map((artifact) => ({
        id: artifact.id,
        courseId: course.id,
        title: artifact.title,
        content: artifact.content,
        moduleId: artifact.scope.type === 'module' ? artifact.scope.moduleId : undefined,
        lessonId: artifact.scope.type === 'lesson' ? artifact.scope.lessonId : undefined,
        citations: artifact.citations,
        approvedAt: artifact.approvedAt ?? artifact.classPublishedAt,
      })),
    },
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
