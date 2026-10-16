import {
  publishCourseResource,
  type PublicationRequest,
} from '@/lib/server/course-resource-publication';
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
  if (!course || course.status !== 'active' || !file?.classVisible || !file.classPublicationId)
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
  const body = (await request.json().catch(() => null)) as {
    action?: string;
    content?: string;
    placement?: PublicationRequest;
  } | null;
  if (body?.action === 'save' || body?.action === 'approve') {
    if (file.classPublicationId) return apiError('INVALID_REQUEST', 409, '已发布文件不能直接修改');
    if (typeof body.content !== 'string' || !body.content.trim())
      return apiError('INVALID_REQUEST', 400, '内容不能为空');
    const content = body.content.trim();
    const status = body.action === 'approve' ? ('ready' as const) : ('draft' as const);
    const updated = await updateServerCourse(course.id, (current) => ({
      ...current,
      updatedAt: Date.now(),
      modules: current.modules.map((module) => ({
        ...module,
        lessons: module.lessons.map((lesson) => ({
          ...lesson,
          files: lesson.files?.map((item) =>
            item.id === fileId ? { ...item, content, status, updatedAt: Date.now() } : item,
          ),
        })),
      })),
    }));
    return apiSuccess({ file: findLessonFile(updated, fileId) });
  }
  if (body?.action === 'unpublish') {
    const updated = await updateServerCourse(course.id, (current) => ({
      ...current,
      updatedAt: Date.now(),
      modules: current.modules.map((courseModule) => ({
        ...courseModule,
        lessons: courseModule.lessons.map((lesson) => ({
          ...lesson,
          files: lesson.files?.map((item) =>
            item.id === fileId
              ? {
                  ...item,
                  classVisible: false,
                  classPublicationId: undefined,
                  classPublishedAt: undefined,
                  publicationPlacement: undefined,
                  updatedAt: Date.now(),
                }
              : item,
          ),
        })),
      })),
    }));
    return apiSuccess({ file: findLessonFile(updated, fileId) });
  }
  if (body?.action !== 'publish') return apiError('INVALID_REQUEST', 400, '不支持的操作');
  try {
    return apiSuccess({
      file: await publishCourseResource(courseId, 'course-file', fileId, body.placement!),
    });
  } catch (error) {
    return apiError('INVALID_REQUEST', 409, error instanceof Error ? error.message : '发布失败');
  }
}

export async function DELETE(
  _req: NextRequest,
  context: { params: Promise<{ courseId: string; fileId: string }> },
) {
  const { courseId, fileId } = await context.params;
  const course = await readServerCourse(courseId);
  if (!course || !findLessonFile(course, fileId))
    return apiError('INVALID_REQUEST', 404, '课程文件不存在');
  await updateServerCourse(course.id, (current) => ({
    ...current,
    updatedAt: Date.now(),
    modules: current.modules.map((courseModule) => ({
      ...courseModule,
      lessons: courseModule.lessons.map((lesson) => ({
        ...lesson,
        files: lesson.files?.filter((item) => item.id !== fileId),
      })),
    })),
  }));
  return apiSuccess({ deleted: fileId });
}
