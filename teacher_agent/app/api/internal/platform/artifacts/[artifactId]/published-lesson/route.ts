import { type NextRequest, NextResponse } from 'next/server';
import { readClassroom } from '@/lib/server/classroom-storage';
import { readCourseArtifact } from '@/lib/server/course-space-storage';
import { classroomView, type ClassroomPayload } from '@/lib/server/platform-learning-projection';

export const dynamic = 'force-dynamic';

/**
 * The teacher-verified published lesson video: course reference, lesson
 * placement and the projected classroom scenes behind it. Reason mirrors the
 * platform's legacy failure messages exactly:
 * not-published → 409 未找到已发布的教学视频,
 * not-a-lesson-video → 409 已发布内容不是课时教学视频,
 * classroom-missing → 404 课堂不存在或尚未发布.
 */
export async function GET(
  request: NextRequest,
  context: { params: Promise<{ artifactId: string }> },
) {
  if (process.env.PLATFORM_AUTH_ENABLED !== 'true' ||
      request.headers.get('x-platform-delegated') !== 'true') {
    return NextResponse.json({ error: 'Platform service authorization required' }, { status: 403 });
  }
  const { artifactId } = await context.params;
  const artifact = await readCourseArtifact(artifactId);
  if (!artifact || artifact.status !== 'published' ||
      artifact.classVisible !== true || !artifact.classPublicationId) {
    return NextResponse.json({ published: false, reason: 'not-published', lesson: null });
  }
  const placement = artifact.publicationPlacement;
  const lessonId = placement?.lessonId;
  const classroomId = artifact.classroomId;
  if (!lessonId || !classroomId) {
    return NextResponse.json({ published: false, reason: 'not-a-lesson-video', lesson: null });
  }
  const classroom = await readClassroom(classroomId);
  if (!classroom) {
    return NextResponse.json({ published: false, reason: 'classroom-missing', lesson: null });
  }
  return NextResponse.json({
    published: true,
    reason: null,
    lesson: {
      courseId: artifact.courseId,
      lessonId,
      classroomId,
      publishedAt: artifact.classPublishedAt,
      classroom: classroomView(classroom as unknown as ClassroomPayload),
    },
  });
}
