import { type NextRequest } from 'next/server';
import { randomUUID } from 'crypto';
import { apiSuccess, apiError, API_ERROR_CODES } from '@/lib/server/api-response';
import {
  buildRequestOrigin,
  isValidClassroomId,
  persistClassroom,
  readClassroom,
  ClassroomSnapshotConflictError,
} from '@/lib/server/classroom-storage';
import { createLogger } from '@/lib/logger';
import {
  prepareClassroomVideo,
  readVideoPlan,
  videoPointer,
  videoStatus,
  nativeVideoConfig,
  videoEnabled,
  readClipCaptions,
} from '@/lib/server/classroom-video';

const log = createLogger('Classroom API');

export async function POST(request: NextRequest) {
  let stageId: string | undefined;
  let sceneCount: number | undefined;
  try {
    const body = await request.json();
    if (body.operation === 'prepare-video') {
      const id = request.nextUrl.searchParams.get('id') || '';
      if (!isValidClassroomId(id) || request.headers.get('x-platform-role') === 'student')
        return apiError(API_ERROR_CODES.INVALID_REQUEST, 403, '无权转换此课件');
      const plan = await prepareClassroomVideo(
        id,
        request.headers.get('x-platform-user-id') || '',
        buildRequestOrigin(request),
      );
      return apiSuccess({ version: plan.version, status: await videoStatus(plan) }, 202);
    }
    const { stage, scenes } = body;
    stageId = stage?.id;
    sceneCount = scenes?.length;

    if (!stage || !scenes) {
      return apiError(
        API_ERROR_CODES.MISSING_REQUIRED_FIELD,
        400,
        'Missing required fields: stage, scenes',
      );
    }

    const id = stage.id || randomUUID();
    if (!isValidClassroomId(id)) {
      return apiError(API_ERROR_CODES.INVALID_REQUEST, 400, 'Invalid classroom id');
    }

    const baseUrl = buildRequestOrigin(request);

    const persisted = await persistClassroom({ id, stage: { ...stage, id }, scenes }, baseUrl, {
      source: 'browser',
    });

    return apiSuccess({ id: persisted.id, url: persisted.url }, 201);
  } catch (error) {
    if (error instanceof ClassroomSnapshotConflictError)
      return apiError(API_ERROR_CODES.INVALID_REQUEST, 409, error.message);
    log.error(
      `Classroom storage failed [stageId=${stageId ?? 'unknown'}, scenes=${sceneCount ?? 0}]:`,
      error,
    );
    return apiError(
      API_ERROR_CODES.INTERNAL_ERROR,
      500,
      'Failed to store classroom',
      error instanceof Error ? error.message : String(error),
    );
  }
}

export async function GET(request: NextRequest) {
  try {
    const id = request.nextUrl.searchParams.get('id');

    if (!id) {
      return apiError(
        API_ERROR_CODES.MISSING_REQUIRED_FIELD,
        400,
        'Missing required parameter: id',
      );
    }

    if (!isValidClassroomId(id)) {
      return apiError(API_ERROR_CODES.INVALID_REQUEST, 400, 'Invalid classroom id');
    }

    const capture = request.nextUrl.searchParams.get('videoCapture');
    if (capture) {
      if (request.headers.get('x-classroom-render-version') !== capture)
        return apiError(API_ERROR_CODES.INVALID_REQUEST, 403, 'Invalid capture grant');
      const plan = await readVideoPlan(id, capture);
      if (!plan) return apiError(API_ERROR_CODES.INVALID_REQUEST, 404, 'Video snapshot not found');
      const sceneId = request.nextUrl.searchParams.get('nativeScene');
      return apiSuccess(
        sceneId ? { nativeConfig: await nativeVideoConfig(plan, sceneId) } : { plan },
      );
    }
    if (request.nextUrl.searchParams.has('video')) {
      const student = request.headers.get('x-platform-role') === 'student';
      const pointer = await videoPointer(
        id,
        student || request.nextUrl.searchParams.get('video') === 'published'
          ? 'published'
          : 'draft',
      );
      const version = student
        ? pointer?.version
        : request.nextUrl.searchParams.get('version') || pointer?.version;
      const plan = version ? await readVideoPlan(id, version) : null;
      if (!plan) return apiSuccess({ manifest: null, enabled: videoEnabled() });
      return apiSuccess({
        enabled: videoEnabled(),
        manifest: {
          version: plan.version,
          title: plan.stage.name,
          stage: plan.stage,
          scenes: plan.scenes,
          status: await videoStatus(plan),
          clips: await Promise.all(
            plan.clips.map(async (c) => ({
              sceneId: c.sceneId,
              url: `/api/classroom-media/${id}/video/${c.key}.mp4`,
              captions: await readClipCaptions(plan, c),
            })),
          ),
        },
      });
    }

    const classroom = await readClassroom(id);
    if (!classroom) {
      return apiError(API_ERROR_CODES.INVALID_REQUEST, 404, 'Classroom not found');
    }

    return apiSuccess({ classroom });
  } catch (error) {
    log.error(
      `Classroom retrieval failed [id=${request.nextUrl.searchParams.get('id') ?? 'unknown'}]:`,
      error,
    );
    return apiError(
      API_ERROR_CODES.INTERNAL_ERROR,
      500,
      'Failed to retrieve classroom',
      error instanceof Error ? error.message : String(error),
    );
  }
}
