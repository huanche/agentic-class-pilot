import { type NextRequest, NextResponse } from 'next/server';
import { readServerCourse } from '@/lib/server/course-space-storage';

export const dynamic = 'force-dynamic';

/**
 * Whether a course material is explicitly published and currently visible —
 * the teacher-owned half of the platform's student material authorization.
 * Mirrors the legacy authorize SQL: the course must be active and the
 * material must carry classVisible with a publication id. Missing course or
 * material simply reports visible=false; the platform turns that into the
 * same 403 its legacy query produced.
 */
export async function GET(
  request: NextRequest,
  context: { params: Promise<{ courseId: string; materialId: string }> },
) {
  if (process.env.PLATFORM_AUTH_ENABLED !== 'true' ||
      request.headers.get('x-platform-delegated') !== 'true') {
    return NextResponse.json({ error: 'Platform service authorization required' }, { status: 403 });
  }
  const { courseId, materialId } = await context.params;
  const course = await readServerCourse(courseId);
  if (!course || course.status !== 'active') {
    return NextResponse.json({ visible: false });
  }
  const material = (course.materials ?? []).find((item) => item.id === materialId);
  return NextResponse.json({
    visible: material?.classVisible === true && !!material.classPublicationId,
  });
}
