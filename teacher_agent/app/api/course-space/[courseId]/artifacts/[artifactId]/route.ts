import { type NextRequest } from 'next/server';
import { nanoid } from 'nanoid';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import {
  readCourseArtifact,
  readServerCourse,
  saveCourseArtifact,
  saveCourseArtifactFile,
  updateCourseJobIfPresent,
} from '@/lib/server/course-space-storage';
import { markdownToArtifactHtml, WORD_ARTIFACT_TYPES } from '@/lib/course-space/artifact-formats';
import { buildCourseArtifactDocx } from '@/lib/server/course-artifact-docx';
import type { CourseArtifactRecord } from '@/lib/course-space/types';

export async function PATCH(
  req: NextRequest,
  context: { params: Promise<{ courseId: string; artifactId: string }> },
) {
  const { courseId, artifactId } = await context.params;
  const [course, artifact] = await Promise.all([
    readServerCourse(courseId),
    readCourseArtifact(artifactId),
  ]);
  // `courseId` may be a platform UUID; artifacts are keyed by the id the course
  // was created under, so compare against the canonical course id.
  if (!course || !artifact || artifact.courseId !== course.id) {
    return apiError('INVALID_REQUEST', 404, '待审核产物不存在');
  }
  const body = (await req.json()) as {
    content?: string;
    reviewerNote?: string;
    action?: 'save' | 'approve' | 'activate' | 'deactivate';
  };
  if (body.action === 'activate' || body.action === 'deactivate') {
    const active = body.action === 'activate';
    if (!active) {
      return apiError('INVALID_REQUEST', 409, '产物发布到班级后不可撤回');
    }
    if (course.status !== 'active') {
      return apiError('INVALID_REQUEST', 409, '请先发布课程，再将产物发布到班级');
    }
    if (artifact.classPublicationId) {
      return apiSuccess({ artifact });
    }
    const publishedAt = Date.now();
    const updated = await saveCourseArtifact({
      ...artifact,
      status: 'published',
      approvedAt: artifact.approvedAt ?? publishedAt,
      classVisible: true,
      activatedAt: publishedAt,
      classPublicationId: `CLS-A-${nanoid(12)}`,
      classPublishedAt: publishedAt,
      updatedAt: publishedAt,
    });
    await updateCourseJobIfPresent(artifact.jobId, {
      status: 'approved',
      message: '教师确认并发布到 Class 通道',
    });
    return apiSuccess({ artifact: updated });
  }
  if (artifact.status === 'published') {
    return apiError('INVALID_REQUEST', 409, '已发布产物不可直接修改，请重新生成版本');
  }
  const content = body.content?.trim() ?? artifact.content;
  if (!content) return apiError('INVALID_REQUEST', 400, '审核内容不能为空');
  const approving = body.action === 'approve';
  // Interactive courseware (attached classroom) carries no material citations;
  // its source lineage is the classroom itself, so the citation gate only
  // applies to text artifacts generated from course materials.
  if (approving && !artifact.classroomId && artifact.citations.length === 0) {
    return apiError('INVALID_REQUEST', 409, '产物缺少原始材料引用，不能批准');
  }
  const nextArtifact: CourseArtifactRecord = {
    ...artifact,
    content,
    htmlContent: markdownToArtifactHtml(content),
    reviewerNote: body.reviewerNote?.trim() || undefined,
    status: approving ? 'approved' : 'review',
    approvedAt: approving ? Date.now() : undefined,
    updatedAt: Date.now(),
  };
  if (WORD_ARTIFACT_TYPES.has(nextArtifact.type)) {
    const wordFileName =
      nextArtifact.wordFileName || `${nextArtifact.title.replace(/[\\/:*?"<>|]/g, '_')}.docx`;
    nextArtifact.wordFileName = wordFileName;
    nextArtifact.wordStorageKey = await saveCourseArtifactFile(
      nextArtifact.id,
      wordFileName,
      await buildCourseArtifactDocx(nextArtifact.title, content),
    );
  }
  const updated = await saveCourseArtifact(nextArtifact);
  await updateCourseJobIfPresent(artifact.jobId, {
    status: approving ? 'approved' : 'review',
    message: approving ? '教师审核通过' : '教师已保存修改，等待批准',
  });
  return apiSuccess({ artifact: updated });
}
