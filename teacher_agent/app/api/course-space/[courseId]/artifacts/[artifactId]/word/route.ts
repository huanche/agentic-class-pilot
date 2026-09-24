import { NextResponse } from 'next/server';
import { apiError } from '@/lib/server/api-response';
import { readCourseArtifact, readCourseArtifactFile } from '@/lib/server/course-space-storage';

export async function GET(
  _req: Request,
  context: { params: Promise<{ courseId: string; artifactId: string }> },
) {
  const { courseId, artifactId } = await context.params;
  const artifact = await readCourseArtifact(artifactId);
  if (!artifact || artifact.courseId !== courseId || !artifact.wordStorageKey) {
    return apiError('INVALID_REQUEST', 404, 'Word 产物不存在');
  }
  const bytes = await readCourseArtifactFile(artifact.wordStorageKey);
  const encoded = encodeURIComponent(artifact.wordFileName || `${artifact.title}.docx`);
  return new NextResponse(new Uint8Array(bytes), {
    headers: {
      'content-type': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      'content-disposition': `attachment; filename*=UTF-8''${encoded}`,
      'content-length': String(bytes.length),
    },
  });
}
