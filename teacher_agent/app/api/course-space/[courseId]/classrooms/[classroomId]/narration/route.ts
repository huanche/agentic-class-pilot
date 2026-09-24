import { type NextRequest } from 'next/server';
import { apiError, apiSuccess, API_ERROR_CODES } from '@/lib/server/api-response';
import {
  buildRequestOrigin,
  isValidClassroomId,
  persistClassroom,
  readClassroom,
} from '@/lib/server/classroom-storage';
import { generateTTSForClassroom } from '@/lib/server/classroom-media-generation';
import { readClassroomBindingFromDatabase } from '@/lib/server/course-space-database';
import { createLogger } from '@/lib/logger';

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

    const classroom = await readClassroom(classroomId);
    if (!classroom) {
      return apiError(API_ERROR_CODES.INVALID_REQUEST, 404, 'Classroom not found');
    }

    const result = await generateTTSForClassroom(
      classroom.scenes,
      classroomId,
      buildRequestOrigin(request),
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
    log.error(`Narration regeneration failed [course=${courseId}, classroom=${classroomId}]`, error);
    return apiError(
      API_ERROR_CODES.INTERNAL_ERROR,
      500,
      'Failed to regenerate classroom narration',
      error instanceof Error ? error.message : String(error),
    );
  }
}
