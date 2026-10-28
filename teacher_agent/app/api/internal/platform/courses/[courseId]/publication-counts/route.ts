import { type NextRequest, NextResponse } from 'next/server';
import { listStoredCourseArtifacts, readServerCourse } from '@/lib/server/course-space-storage';

export const dynamic = 'force-dynamic';

/** Teacher-owned counts with the legacy platform queries' exact filters. */
export async function GET(
  request: NextRequest,
  context: { params: Promise<{ courseId: string }> },
) {
  if (process.env.PLATFORM_AUTH_ENABLED !== 'true' ||
      request.headers.get('x-platform-delegated') !== 'true') {
    return NextResponse.json({ error: 'Platform service authorization required' }, { status: 403 });
  }
  const { courseId } = await context.params;
  const course = await readServerCourse(courseId);
  if (!course) return NextResponse.json({ error: 'Course not found' }, { status: 404 });
  const artifacts = await listStoredCourseArtifacts(course.id);
  const publishedWithClassroom = artifacts.filter(
    (artifact) => artifact.status === 'published' && Boolean(artifact.classroomId),
  );
  return NextResponse.json({
    distinctClassrooms: new Set(publishedWithClassroom.map((artifact) => artifact.classroomId)).size,
    publishedArtifactsWithClassroom: publishedWithClassroom.length,
  });
}
