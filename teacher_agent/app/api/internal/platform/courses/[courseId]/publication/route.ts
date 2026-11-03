import { type NextRequest, NextResponse } from 'next/server';
import {
  readPublishedKnowledgePackage,
  readServerCourse,
} from '@/lib/server/course-space-storage';

export const dynamic = 'force-dynamic';

/** A narrow, read-only publication verdict for the platform. */
export async function GET(
  request: NextRequest,
  context: { params: Promise<{ courseId: string }> },
) {
  // The middleware strips caller-supplied delegation headers and only restores
  // this one after the platform validates the service key and subject.
  if (process.env.PLATFORM_AUTH_ENABLED !== 'true' ||
      request.headers.get('x-platform-delegated') !== 'true') {
    return NextResponse.json({ error: 'Platform service authorization required' }, { status: 403 });
  }
  const { courseId } = await context.params;
  const course = await readServerCourse(courseId);
  if (!course || course.status !== 'active') {
    return NextResponse.json({ published: false, publication: null });
  }
  const knowledgePackage = await readPublishedKnowledgePackage(course.id);
  if (!knowledgePackage || knowledgePackage.status !== 'published') {
    return NextResponse.json({ published: false, publication: null });
  }
  return NextResponse.json({
    published: true,
    publication: {
      publicationId: knowledgePackage.id,
      version: knowledgePackage.version,
    },
  });
}
