import { nanoid } from 'nanoid';
import { NextResponse, type NextRequest } from 'next/server';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import { markdownToArtifactHtml } from '@/lib/course-space/artifact-formats';
import { readServerCourse, updateServerCourse } from '@/lib/server/course-space-storage';

function findLessonFile(course: Awaited<ReturnType<typeof readServerCourse>>, fileId: string) {
  return course?.modules
    .flatMap((module) => module.lessons)
    .flatMap((lesson) => lesson.files ?? [])
    .find((item) => item.id === fileId);
}

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ courseId: string; fileId: string }> },
) {
  const { courseId, fileId } = await context.params;
  const course = await readServerCourse(courseId);
  const file = findLessonFile(course, fileId);
  if (!course || !file?.classPublicationId)
    return apiError('INVALID_REQUEST', 404, '已发布课时文件不存在');
  const body = markdownToArtifactHtml(`# ${file.title}\n\n${file.content}`);
  const requestedSource = new URL(request.url).searchParams.get('from');
  const source =
    requestedSource && /^\/classes\/[A-Za-z0-9_-]+$/.test(requestedSource)
      ? requestedSource
      : `/classes/${courseId}`;
  return new NextResponse(
    `<!doctype html><html><head><meta charset="utf-8"><title>课程文件</title><style>body{font:16px/1.75 system-ui;color:#172033;max-width:960px;margin:0 auto;padding:42px}.back{display:inline-flex;margin-bottom:24px;color:#B00055;text-decoration:none;font-weight:600}h1,h2,h3{color:#101828}</style></head><body><a class="back" href="${source}">← 返回班级</a>${body}</body></html>`,
    {
      headers: { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'private, no-store' },
    },
  );
}

export async function PATCH(
  request: NextRequest,
  context: { params: Promise<{ courseId: string; fileId: string }> },
) {
  const { courseId, fileId } = await context.params;
  const course = await readServerCourse(courseId);
  const file = findLessonFile(course, fileId);
  if (!course || !file) return apiError('INVALID_REQUEST', 404, '课时文件不存在');
  if (course.status !== 'active') return apiError('INVALID_REQUEST', 409, '请先开启 Class 通道');
  const body = (await request.json().catch(() => null)) as { action?: string } | null;
  if (body?.action !== 'publish') return apiError('INVALID_REQUEST', 400, '不支持的操作');
  if (file.classPublicationId) return apiSuccess({ file });
  const now = Date.now();
  const publicationId = `CLS-F-${nanoid(12)}`;
  const updated = await updateServerCourse(courseId, (current) => ({
    ...current,
    modules: current.modules.map((module) => ({
      ...module,
      lessons: module.lessons.map((lesson) => ({
        ...lesson,
        files: lesson.files?.map((item) =>
          item.id === fileId
            ? {
                ...item,
                status: 'ready',
                classVisible: true,
                classPublicationId: publicationId,
                classPublishedAt: now,
                updatedAt: now,
              }
            : item,
        ),
      })),
    })),
  }));
  return apiSuccess({ file: findLessonFile(updated, fileId) });
}
