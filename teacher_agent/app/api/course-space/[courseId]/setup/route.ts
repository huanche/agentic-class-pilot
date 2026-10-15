import { registerCourseWithPlatform } from '@/lib/server/platform-course-bridge';
import { type NextRequest } from 'next/server';
import { nanoid } from 'nanoid';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import { buildOnboardingSchedule } from '@/lib/server/course-onboarding';
import {
  listCourseArtifacts,
  readMaterialExtraction,
  readServerCourse,
  saveCourseArtifact,
  updateServerCourse,
} from '@/lib/server/course-space-storage';
import { markdownToArtifactHtml } from '@/lib/course-space/artifact-formats';
export async function POST(req: NextRequest, context: { params: Promise<{ courseId: string }> }) {
  const { courseId } = await context.params;
  const body = await req.json().catch(() => null);
  const course = await readServerCourse(courseId);
  if (!course || !body) return apiError('INVALID_REQUEST', 400, '课程或建课请求不存在');
  try {
    const artifacts = await listCourseArtifacts(course.id);
    if (body.action === 'import-outline') {
      const material = course.materials.find(
        (item) => item.id === body.materialId && item.purpose === 'course-outline',
      );
      if (!material || material.status !== 'ready') throw new Error('请先上传并完成大纲解析');
      const previous = artifacts.find(
        (item) => item.type === 'course-outline' && item.sourceMaterialId === material.id,
      );
      if (previous) return apiSuccess({ artifact: previous });
      const extraction = await readMaterialExtraction(material.id);
      if (!extraction?.text.trim() || !extraction.chunks.length)
        throw new Error('大纲没有可审核的解析内容，请更换文件');
      const artifact = await saveCourseArtifact({
        id: nanoid(14),
        jobId: `imported_${nanoid(10)}`,
        teacherId: course.teacherId,
        courseId: course.id,
        type: 'course-outline',
        scope: { type: 'course' },
        sourceMaterialId: material.id,
        title: `${course.title}｜课程大纲`,
        content: extraction.text,
        htmlContent: markdownToArtifactHtml(extraction.text),
        status: 'review',
        citations: extraction.chunks.map((chunk) => ({
          materialId: material.id,
          sourceName: material.name,
          page: chunk.page,
          sourceSha256: extraction.sourceSha256,
        })),
        createdAt: Date.now(),
        updatedAt: Date.now(),
      });
      return apiSuccess({ artifact });
    }
    const sources = course.materials.filter((item) => item.purpose !== 'course-outline');
    if (!sources.length || sources.some((item) => item.status !== 'ready'))
      throw new Error('请先完成全部课程资料的上传与解析');
    const outline = artifacts.find(
      (item) =>
        item.id === (body.outlineArtifactId ?? course.onboarding?.outlineArtifactId) &&
        item.type === 'course-outline' &&
        ['approved', 'published'].includes(item.status),
    );
    if (body.action === 'advance' && body.step === 2) {
      const updated = await updateServerCourse(courseId, (current) => ({
        ...current,
        onboarding: { version: 1, ...current.onboarding, step: 2 },
      }));
      return apiSuccess({ course: updated });
    }
    if ((body.action === 'advance' && body.step === 3) || body.action === 'complete') {
      if (!outline) throw new Error('请先保存并审核通过课程大纲');
      const updated = await updateServerCourse(courseId, (current) => {
        const withOutline = {
          ...current,
          onboarding: {
            version: 1 as const,
            ...current.onboarding,
            step: 3 as const,
            outlineArtifactId: outline.id,
          },
        };
        return body.action === 'complete'
          ? buildOnboardingSchedule(withOutline, body.schedule)
          : withOutline;
      });
      if (body.action === 'complete') {
        try {
          await registerCourseWithPlatform(updated);
        } catch {
          await updateServerCourse(courseId, (current) => ({
            ...current,
            onboarding: { version: 1, ...current.onboarding, step: 3, completedAt: undefined },
          }));
          throw new Error(
            '课程目录已保存，但平台课程信息同步失败，请重试完成建课；已有目录不会重复创建',
          );
        }
      }
      return apiSuccess({ course: updated });
    }
    return apiError('INVALID_REQUEST', 400, '不支持的建课步骤');
  } catch (error) {
    return apiError(
      'INVALID_REQUEST',
      409,
      error instanceof Error ? error.message : '保存建课设置失败',
    );
  }
}
