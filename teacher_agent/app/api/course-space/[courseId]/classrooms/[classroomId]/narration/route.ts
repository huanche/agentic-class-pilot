import { type NextRequest } from 'next/server';
import { apiError, apiSuccess, API_ERROR_CODES } from '@/lib/server/api-response';
import {
  buildRequestOrigin,
  ClassroomSnapshotConflictError,
  isValidClassroomId,
  persistClassroom,
  readClassroom,
} from '@/lib/server/classroom-storage';
import { generateTTSForClassroom } from '@/lib/server/classroom-media-generation';
import { readClassroomBindingFromDatabase } from '@/lib/server/course-space-database';
import { createLogger } from '@/lib/logger';
import { getPlatformUserModelConfigForRequest } from '@/lib/server/platform-user-model-config';

const log = createLogger('ClassroomNarration');

export const maxDuration = 300;

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ courseId: string; classroomId: string }> },
) {
  const { courseId, classroomId } = await params;
  if (!isValidClassroomId(classroomId)) {
    return apiError(API_ERROR_CODES.INVALID_REQUEST, 400, 'Invalid classroom id');
  }

  try {
    const binding = await readClassroomBindingFromDatabase(classroomId);
    if (!binding || binding.courseId !== courseId) {
      return apiError(API_ERROR_CODES.INVALID_REQUEST, 404, 'Classroom not found in this course');
    }

    const body = await request.json().catch(() => null);
    if (body?.operation === 'trial-revise') {
      const { readServerCourse } = await import('@/lib/server/course-space-storage');
      const course = await readServerCourse(courseId);
      if (!course || (process.env.PLATFORM_AUTH_ENABLED === 'true' &&
        (request.headers.get('x-platform-role') === 'student' ||
          (request.headers.get('x-platform-user-id') !== course.teacherId && request.headers.get('x-platform-admin') !== 'true'))))
        return apiError('INVALID_REQUEST', 403, '无权修改试用课件');
      const config = await getPlatformUserModelConfigForRequest(request);
      const { reviseTrialNarration } = await import('@/lib/server/courseware-trial-narration');
      const result = await reviseTrialNarration(classroomId, body, buildRequestOrigin(request), course.teacherId, config, request.signal);
      return apiSuccess(result);
    }
    const classroom = await readClassroom(classroomId);
    if (!classroom) {
      return apiError(API_ERROR_CODES.INVALID_REQUEST, 404, 'Classroom not found');
    }

    const byok = await getPlatformUserModelConfigForRequest(request);
    const result = await generateTTSForClassroom(
      classroom.scenes,
      classroomId,
      buildRequestOrigin(request),
      byok?.tts,
      { languageDirective: classroom.stage.languageDirective },
    );
    if (result.generated === 0) {
      return apiError(
        API_ERROR_CODES.GENERATION_FAILED,
        502,
        result.failed > 0
          ? 'Narration generation failed for every speech action'
          : 'The classroom has no speech actions or no server TTS provider is available',
      );
    }

    await persistClassroom(
      { id: classroom.id, stage: classroom.stage, scenes: classroom.scenes },
      buildRequestOrigin(request),
    );
    return apiSuccess({ classroomId, ...result });
  } catch (error) {
    if (error instanceof ClassroomSnapshotConflictError)
      return apiError('INVALID_REQUEST', 409, error.message);
    log.error(`Narration regeneration failed [course=${courseId}, classroom=${classroomId}]`, error);
    return apiError(
      API_ERROR_CODES.INTERNAL_ERROR,
      500,
      'Failed to regenerate classroom narration',
      error instanceof Error ? error.message : String(error),
    );
  }
}
