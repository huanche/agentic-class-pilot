import { type NextRequest, NextResponse } from 'next/server';
import { readClassroom } from '@/lib/server/classroom-storage';
import { isCourseDatabaseConfigured, latestPublishedClassroomIdFromDatabase } from '@/lib/server/course-space-database';
import { listStoredCourseArtifacts, readServerCourse } from '@/lib/server/course-space-storage';

export const dynamic = 'force-dynamic';

/** Resolve only the current published classroom identity for platform launch. */
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
  if (!course || course.status !== 'active') {
    return NextResponse.json({ classroomId: null });
  }
  if (isCourseDatabaseConfigured()) {
    return NextResponse.json({
      classroomId: await latestPublishedClassroomIdFromDatabase(course.id) ?? null,
    });
  }
  const artifacts = await listStoredCourseArtifacts(course.id);
  const candidates = artifacts
    .filter((artifact) => artifact.status === 'published' &&
      artifact.classVisible === true && artifact.classPublicationId != null &&
      artifact.classroomId != null)
    .sort((a, b) => (b.classPublishedAt ?? -Infinity) - (a.classPublishedAt ?? -Infinity));
  for (const artifact of candidates) {
    if (artifact.classroomId && await readClassroom(artifact.classroomId)) {
      return NextResponse.json({ classroomId: artifact.classroomId });
    }
  }
  return NextResponse.json({ classroomId: null });
}
