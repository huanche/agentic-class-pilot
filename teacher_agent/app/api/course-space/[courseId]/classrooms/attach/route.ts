import { type NextRequest } from 'next/server';
import { nanoid } from 'nanoid';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import {
  listCourseArtifacts,
  readServerCourse,
  saveCourseArtifact,
  updateServerCourse,
} from '@/lib/server/course-space-storage';
import type { CourseArtifactJob, CourseArtifactRecord } from '@/lib/course-space/types';
import { readClassroom } from '@/lib/server/classroom-storage';

type ClassroomInput = { id: string; title?: string };

function isSafeId(value: string) {
  return /^[a-zA-Z0-9_-]+$/.test(value);
}

export async function POST(req: NextRequest, context: { params: Promise<{ courseId: string }> }) {
  const { courseId } = await context.params;
  const course = await readServerCourse(courseId);
  if (!course) return apiError('INVALID_REQUEST', 404, '课程不存在');

  const body = (await req.json()) as {
    classrooms?: ClassroomInput[];
    classroomId?: string;
    title?: string;
    scope?: CourseArtifactJob['scope'];
    moduleTitle?: string;
    lessonTitle?: string;
  };
  const classrooms = body.classrooms ?? (body.classroomId ? [{ id: body.classroomId, title: body.title }] : []);
  if (classrooms.length === 0 || classrooms.some((item) => !isSafeId(item.id))) {
    return apiError('INVALID_REQUEST', 400, '课堂标识无效');
  }

  let scope = body.scope;
  let savedCourse = course;
  if (!scope && body.moduleTitle && body.lessonTitle) {
    const courseModule = course.modules.find((item) => item.title === body.moduleTitle);
    if (!courseModule) return apiError('INVALID_REQUEST', 404, '目标课程模块不存在');
    let lesson = courseModule.lessons.find((item) => item.title === body.lessonTitle);
    if (!lesson) {
      const now = Date.now();
      lesson = {
        id: nanoid(10), moduleId: courseModule.id, title: body.lessonTitle.trim(),
        order: courseModule.lessons.length + 1, objectives: [], materialIds: [],
        createdAt: now, updatedAt: now,
      };
      const lessonToAdd = lesson;
      savedCourse = await updateServerCourse(courseId, (current) => ({
        ...current,
        modules: current.modules.map((item) => item.id === courseModule.id
          ? { ...item, lessons: [...item.lessons, lessonToAdd], updatedAt: now }
          : item),
      }));
    }
    scope = { type: 'lesson', lessonId: lesson.id };
  }
  scope ??= { type: 'course' };

  const scopeExists = scope.type === 'course'
    || (scope.type === 'module' && savedCourse.modules.some((item) => item.id === scope.moduleId))
    || (scope.type === 'lesson' && savedCourse.modules.some((item) => item.lessons.some((lesson) => lesson.id === scope.lessonId)));
  if (!scopeExists) return apiError('INVALID_REQUEST', 400, '归档位置不属于当前课程');

  const existing = await listCourseArtifacts(courseId);
  const now = Date.now();
  const artifacts: CourseArtifactRecord[] = [];
  for (const classroom of classrooms) {
    if (!await readClassroom(classroom.id)) {
      return apiError('INVALID_REQUEST', 404, `课堂 ${classroom.id} 的课件本体不存在，不能建立悬空产物索引`);
    }
    const duplicate = existing.find((item) => item.classroomId === classroom.id);
    if (duplicate) {
      const updated = await saveCourseArtifact({ ...duplicate, scope, updatedAt: now });
      artifacts.push(updated);
      continue;
    }
    const title = classroom.title?.trim() || `${savedCourse.title}｜互动课件`;
    artifacts.push(await saveCourseArtifact({
      id: nanoid(14),
      jobId: `attached_${nanoid(10)}`,
      teacherId: savedCourse.teacherId,
      courseId,
      scope,
      type: 'lesson-courseware',
      title,
      content: `互动课件已归档到当前课程。\n\n课堂地址：/classroom/${classroom.id}`,
      htmlContent: `<h1>${title.replace(/[<>&"']/g, '')}</h1><p>互动课件已归档到当前课程。</p>`,
      status: 'review',
      citations: [],
      classroomId: classroom.id,
      classroomUrl: `/classroom/${classroom.id}`,
      createdAt: now,
      updatedAt: now,
    }));
  }

  return apiSuccess({ course: savedCourse, artifacts, scope });
}
