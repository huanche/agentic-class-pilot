import { type NextRequest, NextResponse } from 'next/server';
import {
  isCourseDatabaseConfigured,
  readClassroomBindingFromDatabase,
} from '@/lib/server/course-space-database';
import { listStoredCourseArtifacts, readServerCourse } from '@/lib/server/course-space-storage';

export const dynamic = 'force-dynamic';

/**
 * Teacher-owned classroom facts for the platform's authorization: the
 * classroom→course mapping (any course state, like the legacy lookup) and
 * whether the classroom is the currently published, visible classroom of an
 * active course (the student-player half). courseId is the teacher service's
 * own course reference; the platform resolves it to its own records.
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
  // Classroom→course linkage lives in the course database only; the legacy
  // authorize path had the same requirement (mentra_classrooms).
  if (!isCourseDatabaseConfigured()) {
    return NextResponse.json({ courseId: null, published: false });
  }
  const binding = await readClassroomBindingFromDatabase(classroomId);
  if (!binding?.courseId) {
    return NextResponse.json({ courseId: null, published: false });
  }
  const course = await readServerCourse(binding.courseId);
  if (!course) {
    return NextResponse.json({ courseId: null, published: false });
  }
  // The mapping survives any course state so teachers keep reviewing drafts;
  // only the student verdict requires an active course.
  const published = course.status === 'active' &&
    (await listStoredCourseArtifacts(course.id)).some(
      (artifact) => artifact.status === 'published' &&
        artifact.classVisible === true && artifact.classPublicationId != null &&
        artifact.classroomId === classroomId,
    );
  return NextResponse.json({ courseId: course.id, published });
}
