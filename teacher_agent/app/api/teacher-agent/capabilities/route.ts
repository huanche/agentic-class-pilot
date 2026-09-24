import { apiSuccess } from '@/lib/server/api-response';

export const runtime = 'nodejs';

export async function GET() {
  return apiSuccess({
    service: 'teacher-agent-api',
    protocolVersion: '1.0',
    entries: {
      teacherWorkspace: '/teacher-workspace?workspace={courseId}',
      classroomPlayer: '/classroom-player/{classroomId}',
    },
    capabilities: [
      'teacher-operation-planning',
      'teacher-operation-execution',
      'courseware-generation',
      'knowledge-graph',
      'artifact-review',
    ],
    legacyRoutesPreserved: true,
  });
}
