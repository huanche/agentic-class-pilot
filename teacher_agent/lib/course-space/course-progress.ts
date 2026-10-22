import type { CourseArtifactRecord, CourseSpace } from './types';
export type CourseStatusTarget = {
  folder: 'materials' | 'outline' | 'courseware';
  fileId?: string;
  lessonId?: string;
};
export type CourseTodo = { title: string; target: CourseStatusTarget };
export function summarizeCourseProgress(course: CourseSpace, artifacts: CourseArtifactRecord[]) {
  const materials = course.materials.filter((item) => item.purpose !== 'course-outline');
  const lessons = course.modules.flatMap((item) => item.lessons);
  const outlines = artifacts
    .filter((item) => item.type === 'course-outline')
    .sort((a, b) => b.updatedAt - a.updatedAt);
  const outline =
    outlines.find((item) => item.id === course.onboarding?.outlineArtifactId) ?? outlines[0];
  const outlineReady = Boolean(outline && ['approved', 'published'].includes(outline.status));
  const scoped = (id: string) =>
    artifacts.filter(
      (item) =>
        (item.scope.type === 'lesson' && item.scope.lessonId === id) ||
        item.publicationPlacement?.lessonId === id,
    );
  const prepared = lessons.filter(
    (lesson) =>
      ['lesson-objectives', 'knowledge-points'].every((type) =>
        lesson.files?.some((file) => file.type === type && file.status === 'ready'),
      ) &&
      scoped(lesson.id).some(
        (item) =>
          item.type === 'lesson-courseware' && ['approved', 'published'].includes(item.status),
      ),
  ).length;
  const published = lessons.filter((lesson) =>
    scoped(lesson.id).some(
      (item) =>
        item.type === 'lesson-courseware' &&
        item.status === 'published' &&
        item.classVisible &&
        item.classPublicationId &&
        item.publicationPlacement?.lessonId === lesson.id,
    ),
  ).length;
  const todos: CourseTodo[] = [];
  const pendingMaterials = materials.filter((item) => item.status !== 'ready');
  if (!materials.length)
    todos.push({ title: '上传并解析课程资料', target: { folder: 'materials' } });
  else if (pendingMaterials.length)
    todos.push({
      title: `${pendingMaterials.length}份资料${pendingMaterials.some((item) => item.status === 'failed') ? '待重试解析' : '待完成解析'}`,
      target: { folder: 'materials', fileId: pendingMaterials[0].id },
    });
  if (!outlineReady)
    todos.push({
      title: outline ? '审核课程大纲' : '生成或上传课程大纲',
      target: { folder: 'outline', fileId: outline?.id },
    });
  const missingDocuments = lessons.filter((lesson) =>
    ['lesson-objectives', 'knowledge-points'].some(
      (type) => !lesson.files?.some((file) => file.type === type && file.content.trim()),
    ),
  );
  if (missingDocuments.length)
    todos.push({
      title: `${missingDocuments.length}个课次待补齐目标或知识点`,
      target: { folder: 'courseware', lessonId: missingDocuments[0].id },
    });
  const missingCourseware = lessons.filter(
    (lesson) => !scoped(lesson.id).some((item) => item.type === 'lesson-courseware'),
  );
  if (missingCourseware.length)
    todos.push({
      title: `${missingCourseware.length}个课次待生成课件`,
      target: { folder: 'courseware', lessonId: missingCourseware[0].id },
    });
  const reviewFiles = lessons.flatMap((lesson) =>
    (lesson.files ?? [])
      .filter((file) => file.status !== 'ready' && file.content.trim())
      .map((file) => ({ file, lesson })),
  );
  const reviewArtifacts = artifacts.filter(
    (item) =>
      item.type !== 'course-outline' &&
      item.type !== 'lesson-courseware' &&
      ['draft', 'review'].includes(item.status),
  );
  if (reviewFiles.length || reviewArtifacts.length)
    todos.push({
      title: `${reviewFiles.length + reviewArtifacts.length}份教学文件待审核`,
      target: reviewFiles.length
        ? {
            folder: 'courseware',
            fileId: reviewFiles[0].file.id,
            lessonId: reviewFiles[0].lesson.id,
          }
        : { folder: 'courseware', fileId: reviewArtifacts[0].id },
    });
  const resources = [
    ...artifacts,
    ...course.materials,
    ...lessons.flatMap((lesson) => lesson.files ?? []),
  ];
  const unassigned = resources.filter(
    (item) => item.classPublicationId && !item.publicationPlacement,
  );
  if (unassigned.length)
    todos.push({
      title: `${unassigned.length}份已发布文件待确认课时归属`,
      target: { folder: 'courseware', fileId: unassigned[0].id },
    });
  const unpublished = artifacts.filter(
    (item) =>
      item.type === 'lesson-courseware' &&
      ['draft', 'review', 'approved'].includes(item.status) &&
      !item.classPublicationId,
  );
  if (unpublished.length)
    todos.push({
      title: `${unpublished.length}份课件待发布`,
      target: { folder: 'courseware', fileId: unpublished[0].id },
    });
  if (!lessons.length)
    todos.push({ title: '建立周次和课次目录', target: { folder: 'courseware' } });
  return {
    materialReady: materials.filter((item) => item.status === 'ready').length,
    materialTotal: materials.length,
    outlineReady,
    prepared,
    published,
    lessonTotal: lessons.length,
    percent: lessons.length ? Math.round((prepared / lessons.length) * 100) : 0,
    todos,
  };
}
