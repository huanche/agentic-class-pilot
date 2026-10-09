import { nanoid } from 'nanoid';
import { type NextRequest } from 'next/server';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import {
  listCourseArtifacts,
  listKnowledgePackages,
  readServerCourse,
  saveKnowledgePackage,
  updateServerCourse,
} from '@/lib/server/course-space-storage';
import type { PublishedKnowledgePackage } from '@/lib/course-space/types';

export async function POST(_req: NextRequest, context: { params: Promise<{ courseId: string }> }) {
  const { courseId } = await context.params;
  const course = await readServerCourse(courseId);
  if (!course) return apiError('INVALID_REQUEST', 404, '课程不存在');
  // Artifacts and packages are keyed by the id the course was created under;
  // platform UUID entry points must publish under that canonical id so the
  // new package aligns with existing artifacts and versions.
  const canonicalId = course.id;
  const artifacts = await listCourseArtifacts(canonicalId);
  if (course.status === 'archived') return apiError('INVALID_REQUEST', 409, '归档课程不能发布');
  // Opening a course never implicitly publishes reviewed/generated files.
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
    version: (previous[0]?.version ?? 0) + 1,
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
  // Insert the successor BEFORE retiring the previous package: an interruption
  // between the two writes must never leave the course without any published
  // package (readPublishedKnowledgePackage picks the highest version, so a
  // crash after the insert self-heals on the next publish).
  await saveKnowledgePackage(pkg);
  await Promise.all(
    previous
      .filter((item) => item.status === 'published')
      .map((item) => saveKnowledgePackage({ ...item, status: 'superseded' })),
  );
  await updateServerCourse(canonicalId, (current) => ({
    ...current,
    status: 'active',
    activeKnowledgePackageId: pkg.id,
  }));
  return apiSuccess({ knowledgePackage: pkg }, 201);
}
