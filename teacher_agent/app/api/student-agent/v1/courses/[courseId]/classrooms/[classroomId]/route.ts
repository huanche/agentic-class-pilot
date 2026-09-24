import { type NextRequest } from 'next/server';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import { authorizeStudentAgent } from '@/lib/server/student-agent-auth';
import { readClassroom } from '@/lib/server/classroom-storage';
import { listCourseArtifacts, readPublishedKnowledgePackage } from '@/lib/server/course-space-storage';

export async function GET(request: NextRequest, context: { params: Promise<{ courseId: string; classroomId: string }> }) {
  const denied = authorizeStudentAgent(request);
  if (denied) return denied;
  const { courseId, classroomId } = await context.params;
  const [artifacts, knowledgePackage] = await Promise.all([
    listCourseArtifacts(courseId),
    readPublishedKnowledgePackage(courseId),
  ]);
  const linked = artifacts.some((artifact) =>
    artifact.status === 'published' && artifact.classroomId === classroomId,
  );
  if (!linked || !knowledgePackage) return apiError('INVALID_REQUEST', 404, '已发布课件不存在');
  const classroom = await readClassroom(classroomId);
  if (!classroom) return apiError('INVALID_REQUEST', 410, '课件索引存在，但课件本体不可用');
  return apiSuccess({ schemaVersion: '1.0', classroom });
}
