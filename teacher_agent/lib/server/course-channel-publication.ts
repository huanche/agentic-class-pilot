import { nanoid } from 'nanoid';
import type { CourseSpace, PublishedKnowledgePackage } from '@/lib/course-space/types';
import {
  listCourseArtifacts,
  listKnowledgePackages,
  saveKnowledgePackage,
  updateServerCourse,
} from './course-space-storage';

/** Initialize the student-facing course package using only explicit publications. */
export async function publishCourseChannel(course: CourseSpace) {
  if (course.status === 'archived') throw new Error('归档课程不能发布');
  const canonicalId = course.id;
  const artifacts = await listCourseArtifacts(canonicalId);
  const published = artifacts.filter(
    (artifact) =>
      artifact.status === 'published' &&
      artifact.classVisible === true &&
      artifact.classPublicationId,
  );
  const previous = await listKnowledgePackages(canonicalId);
  const now = Date.now();
  const pkg: PublishedKnowledgePackage = {
    id: nanoid(14),
    teacherId: course.teacherId,
    courseId: canonicalId,
    version: Math.max(0, ...previous.map((item) => item.version)) + 1,
    status: 'published',
    entries: published.map((artifact) => ({
      id: nanoid(14),
      courseId: canonicalId,
      moduleId: artifact.scope.type === 'module' ? artifact.scope.moduleId : undefined,
      lessonId: artifact.scope.type === 'lesson' ? artifact.scope.lessonId : undefined,
      title: artifact.title,
      content: artifact.content,
      citations: artifact.citations,
      approvedAt: artifact.approvedAt || now,
    })),
    createdAt: now,
    publishedAt: now,
  };
  // Insert first: an interrupted write must leave a published package available.
  await saveKnowledgePackage(pkg);
  await Promise.all(
    previous
      .filter((item) => item.status === 'published')
      .map((item) => saveKnowledgePackage({ ...item, status: 'superseded' })),
  );
  await updateServerCourse(canonicalId, (current) => {
    if (current.status === 'archived') throw new Error('归档课程不能发布');
    return { ...current, status: 'active', activeKnowledgePackageId: pkg.id };
  });
  return pkg;
}
