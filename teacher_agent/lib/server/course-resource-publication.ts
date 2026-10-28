import { nanoid } from 'nanoid';
import type { CoursePublicationPlacement, CourseSpace } from '@/lib/course-space/types';
import {
  readServerCourse,
  readCourseArtifact,
  readCourseJob,
  saveCourseArtifact,
  updateServerCourse,
  updateCourseJobIfPresent,
} from './course-space-storage';
import { publishCourseChannel } from './course-channel-publication';

async function queuePublishedVideo(courseId: string, artifactId: string, classroomId?: string) {
  if (!classroomId || process.env.PLATFORM_AUTH_ENABLED !== 'true') return;
  const response = await fetch(
    `${process.env.PLATFORM_AUTH_URL}/api/v1/internal/teacher/published-lesson-knowledge`,
    { method: 'POST', headers: {
      'Content-Type': 'application/json',
      'X-Teacher-Service-Key': process.env.PLATFORM_SERVICE_KEY || '',
    }, body: JSON.stringify({ course_id: courseId, artifact_id: artifactId }),
      cache: 'no-store', signal: AbortSignal.timeout(10000) },
  );
  if (!response.ok) throw new Error('视频已发布，但知识点准备任务登记失败，请再次点击发布重试');
}
export type PublicationRequest = Omit<CoursePublicationPlacement, 'confirmedAt'> & {
  newLessonTitle?: string;
};
export type PublicationKind = 'artifact' | 'material' | 'course-file';
export function validatePlacement(input: PublicationRequest) {
  if (
    !input ||
    !Number.isInteger(input.week) ||
    input.week < 1 ||
    input.week > 100 ||
    !Number.isInteger(input.lessonNumber) ||
    input.lessonNumber < 1 ||
    input.lessonNumber > 1000 ||
    !Number.isFinite(input.teachingHours) ||
    input.teachingHours <= 0 ||
    input.teachingHours > 24 ||
    !['courseware', 'objectives', 'knowledge-points', 'outline', 'exercise', 'material'].includes(
      input.resourceType,
    )
  )
    throw new Error('请确认有效的资料类型、周次、课次和课时数后再发布');
  if (!input.lessonId && !input.newLessonTitle?.trim())
    throw new Error('请选择所属课时，或先创建新课时');
}
function placementForLesson(course: CourseSpace, input: PublicationRequest) {
  const lesson = course.modules
    .flatMap((courseModule) => courseModule.lessons)
    .find((item) => item.id === input.lessonId);
  if (input.lessonId && !lesson) throw new Error('所选课时不属于当前课程');
  if (
    lesson &&
    ((lesson.week && lesson.week !== input.week) ||
      (lesson.lessonNumber && lesson.lessonNumber !== input.lessonNumber) ||
      (lesson.teachingHours && lesson.teachingHours !== input.teachingHours))
  )
    throw new Error('该课时已有不同的周次或课时信息，请选择正确课时或新建课时');
  if (
    course.modules.some((courseModule) =>
      courseModule.lessons.some(
        (item) =>
          item.id !== input.lessonId &&
          item.week === input.week &&
          item.lessonNumber === input.lessonNumber,
      ),
    )
  )
    throw new Error('该周课次已存在，请选择已有课时，避免重复创建');
}
export async function publishCourseResource(
  courseId: string,
  kind: PublicationKind,
  id: string,
  input: PublicationRequest,
) {
  validatePlacement(input);
  const course = await readServerCourse(courseId);
  if (!course) throw new Error('课程不存在');
  if (course.status === 'archived') throw new Error('归档课程不能发布');
  placementForLesson(course, input);
  const artifact = kind === 'artifact' ? await readCourseArtifact(id) : undefined;
  const resource =
    kind === 'artifact'
      ? artifact
      : kind === 'material'
        ? course.materials.find((item) => item.id === id)
        : course.modules
            .flatMap((courseModule) => courseModule.lessons)
            .flatMap((lesson) => lesson.files ?? [])
            .find((item) => item.id === id);
  if (!resource || (artifact && artifact.courseId !== course.id))
    throw new Error('待发布文件不属于当前课程');
  if (artifact?.type === 'lesson-courseware' && input.resourceType !== 'courseware')
    throw new Error('课件必须以课件类型发布');
  if (artifact?.type === 'lesson-courseware') {
    const job = await readCourseJob(artifact.jobId);
    if (
      job?.backgroundGeneration &&
      (job.backgroundGeneration.completedPages < job.backgroundGeneration.totalPages ||
        !['review', 'approved'].includes(job.status))
    )
      throw new Error('课件尚未完整生成，请等待完成后发布');
  }
  if (kind !== 'artifact' && input.resourceType === 'courseware')
    throw new Error('只有生成的互动课件可以发布为课件');
  const ensureStudentPublication = async () => {
    if (course.status === 'active') return;
    const latest = await readServerCourse(course.id);
    if (!latest) throw new Error('课程不存在');
    if (latest.status !== 'active') await publishCourseChannel(latest);
  };
  if (resource.classPublicationId && resource.publicationPlacement) {
    const previous = resource.publicationPlacement;
    if (
      ['lessonId', 'week', 'lessonNumber', 'teachingHours', 'resourceType'].some(
        (key) => previous[key as keyof typeof previous] !== input[key as keyof PublicationRequest],
      )
    )
      throw new Error('已确认发布的文件不能更改归属，请发布新版本');
    // Retry initialization if a previous publish saved the resource but failed
    // before creating the student package. Preserve the original publication id.
    await ensureStudentPublication();
    if (artifact) await queuePublishedVideo(course.id, artifact.id, artifact.classroomId);
    return resource;
  }
  const now = Date.now();
  const lessonId = input.lessonId || nanoid(14);
  const placement: CoursePublicationPlacement = {
    lessonId,
    week: input.week,
    lessonNumber: input.lessonNumber,
    teachingHours: input.teachingHours,
    resourceType: input.resourceType,
    confirmedAt: now,
  };
  const publicationId =
    resource.classPublicationId ||
    `CLS-${kind === 'artifact' ? 'A' : kind === 'material' ? 'M' : 'F'}-${nanoid(12)}`;
  const fields = {
    publicationPlacement: placement,
    classVisible: true,
    classPublicationId: publicationId,
    classPublishedAt: resource.classPublishedAt ?? now,
    updatedAt: now,
  };
  const updated = await updateServerCourse(course.id, (current) => {
    if (current.status === 'archived') throw new Error('归档课程不能发布');
    placementForLesson(current, input);
    const modules = current.modules.map((courseModule) => ({
      ...courseModule,
      lessons: courseModule.lessons.map((lesson) => ({
        ...lesson,
        materialIds: [...lesson.materialIds],
        files: [...(lesson.files ?? [])],
      })),
    }));
    let target = modules
      .flatMap((courseModule) => courseModule.lessons)
      .find((lesson) => lesson.id === lessonId);
    if (!target) {
      let courseModule = modules.find((item) => !item.id.startsWith('folder-'));
      if (!courseModule) {
        courseModule = {
          id: nanoid(12),
          courseId: current.id,
          title: 'AI课件',
          order: modules.length + 1,
          objectives: [],
          lessons: [],
          createdAt: now,
          updatedAt: now,
        };
        modules.push(courseModule);
      }
      target = {
        id: lessonId,
        moduleId: courseModule.id,
        title: input.newLessonTitle!.trim(),
        order: courseModule.lessons.length + 1,
        objectives: [],
        materialIds: [],
        files: [],
        createdAt: now,
        updatedAt: now,
      };
      courseModule.lessons.push(target);
    }
    Object.assign(target, {
      week: input.week,
      lessonNumber: input.lessonNumber,
      teachingHours: input.teachingHours,
      updatedAt: now,
    });
    if (kind === 'material') {
      for (const courseModule of modules)
        for (const lesson of courseModule.lessons)
          lesson.materialIds = lesson.materialIds.filter((item) => item !== id);
      target.materialIds.push(id);
    }
    if (kind === 'course-file') {
      for (const courseModule of modules)
        for (const lesson of courseModule.lessons)
          lesson.files = lesson.files.filter((item) => item.id !== id);
      const file = resource as import('@/lib/course-space/types').CourseLessonFile;
      if (target.files.some((item) => item.type === file.type))
        throw new Error('目标课时已存在同类型文件，请先核对');
      target.files.push({ ...file, ...fields, lessonId, status: 'ready' });
    }
    return {
      ...current,
      modules,
      materials: current.materials.map((item) =>
        kind === 'material' && item.id === id ? { ...item, ...fields, activatedAt: now } : item,
      ),
      updatedAt: now,
    };
  });
  if (artifact) {
    const saved = await saveCourseArtifact({
      ...artifact,
      ...fields,
      scope: { type: 'lesson', lessonId },
      status: 'published',
      approvedAt: artifact.approvedAt ?? now,
      activatedAt: now,
    });
    await updateCourseJobIfPresent(artifact.jobId, {
      status: 'approved',
      message: '教师已确认课时归属并发布',
    });
    await ensureStudentPublication();
    await queuePublishedVideo(course.id, saved.id, saved.classroomId);
    return saved;
  }
  await ensureStudentPublication();
  return kind === 'material'
    ? updated.materials.find((item) => item.id === id)!
    : updated.modules
        .flatMap((courseModule) => courseModule.lessons)
        .flatMap((lesson) => lesson.files ?? [])
        .find((item) => item.id === id)!;
}
