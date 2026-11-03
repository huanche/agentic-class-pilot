import { type NextRequest, NextResponse } from 'next/server';
import { readClassroom } from '@/lib/server/classroom-storage';
import { classroomView, type ClassroomPayload } from '@/lib/server/platform-learning-projection';

export const dynamic = 'force-dynamic';

/**
 * Projected scenes of one classroom — lets the platform serve old-session
 * replay without reading teacher tables. Null when the snapshot is missing
 * (the platform's legacy replay query returned empty scenes for that).
 */
export async function GET(
  request: NextRequest,
  context: { params: Promise<{ classroomId: string }> },
) {
  if (process.env.PLATFORM_AUTH_ENABLED !== 'true' ||
      request.headers.get('x-platform-delegated') !== 'true') {
    return NextResponse.json({ error: 'Platform service authorization required' }, { status: 403 });
  }
  const { classroomId } = await context.params;
  const classroom = await readClassroom(classroomId);
  if (!classroom) {
    return NextResponse.json({ classroom: null });
  }
  return NextResponse.json({ classroom: classroomView(classroom as unknown as ClassroomPayload) });
}
