import { type NextRequest, NextResponse } from 'next/server';
import { readServerCourse } from '@/lib/server/course-space-storage';

export const dynamic = 'force-dynamic';

/** Small teacher-owned metadata read for the platform's chat history view. */
export async function GET(
  request: NextRequest,
  context: { params: Promise<{ courseId: string }> },
) {
  if (
    process.env.PLATFORM_AUTH_ENABLED !== 'true' ||
    request.headers.get('x-platform-delegated') !== 'true'
  ) {
    return NextResponse.json({ error: 'Platform service authorization required' }, { status: 403 });
  }
  const { courseId } = await context.params;
  const course = await readServerCourse(courseId);
  const titles: Record<string, string> = {};
  for (const module of course?.modules ?? []) {
    for (const lesson of module.lessons ?? []) {
      if (lesson.id) titles[String(lesson.id)] = String(lesson.title || lesson.id);
    }
  }
  return NextResponse.json({ titles });
}
