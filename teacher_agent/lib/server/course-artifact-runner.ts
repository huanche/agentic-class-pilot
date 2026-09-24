import { nanoid } from 'nanoid';
import { callLLM } from '@/lib/ai/llm';
import { generateClassroom } from '@/lib/server/classroom-generation';
import { resolveModel } from '@/lib/server/resolve-model';
import type {
  CourseArtifactJob,
  CourseArtifactRecord,
  CourseArtifactType,
  CourseMaterialExtraction,
  PublishedKnowledgeCitation,
} from '@/lib/course-space/types';
import {
  readMaterialExtraction,
  readServerCourse,
  saveCourseArtifact,
  saveCourseArtifactFile,
  updateCourseJob,
} from '@/lib/server/course-space-storage';
import { markdownToArtifactHtml, WORD_ARTIFACT_TYPES } from '@/lib/course-space/artifact-formats';
import { buildCourseArtifactDocx } from '@/lib/server/course-artifact-docx';

const labels: Record<CourseArtifactType, string> = {
  'course-outline': '课程教学大纲',
  'module-plan': '模块教学计划',
  'lesson-courseware': '课时 PPT / 互动课件',
  narration: '讲稿与配音',
  'exercise-set': '习题与答案',
  'assessment-rubric': '测验与评分量规',
  'pbl-project': 'PBL 项目',
};

function scopeTitle(job: CourseArtifactJob, course: NonNullable<Awaited<ReturnType<typeof readServerCourse>>>) {
  const scope = job.scope;
  if (scope.type === 'course') return course.title;
  if (scope.type === 'module') {
    return course.modules.find((item) => item.id === scope.moduleId)?.title || course.title;
  }
  for (const courseModule of course.modules) {
    const lesson = courseModule.lessons.find((item) => item.id === scope.lessonId);
    if (lesson) return `${courseModule.title} / ${lesson.title}`;
  }
  return course.title;
}

function citationsFor(extractions: CourseMaterialExtraction[], course: NonNullable<Awaited<ReturnType<typeof readServerCourse>>>): PublishedKnowledgeCitation[] {
  return extractions.flatMap((extraction) => {
    const material = course.materials.find((item) => item.id === extraction.materialId);
    if (!material) return [];
    const pages = [...new Set(extraction.chunks.map((chunk) => chunk.page))].slice(0, 20);
    return pages.map((page) => ({
      materialId: material.id,
      sourceName: material.name,
      page,
      ...(material.mimeType.includes('presentation') ? { slide: page } : {}),
      sourceSha256: extraction.sourceSha256,
    }));
  });
}

function sourceContext(extractions: CourseMaterialExtraction[]) {
  return extractions
    .flatMap((item) =>
      item.chunks.map((chunk) =>
        `【来源 material:${item.materialId} page:${chunk.page}】\n${chunk.text}`,
      ),
    )
    .join('\n\n')
    .slice(0, 60000);
}

function artifactInstruction(type: CourseArtifactType) {
  const common = '必须忠于教师材料，不得虚构来源；使用 Markdown；关键结论后标注 [material:材料ID page:页码]。';
  const specific: Record<CourseArtifactType, string> = {
    'course-outline': '生成课程目标、模块结构、课时安排、重点难点、评价方式和材料映射。',
    'module-plan': '生成模块目标、先备知识、课时序列、教学活动、形成性评价和作业。',
    'lesson-courseware': '生成可用于课堂讲解的逐页课件结构。',
    narration: '生成逐课时讲稿，包含自然过渡、公式物理意义和重要概念解释，避免照读页面。',
    'exercise-set': '生成分层习题、参考答案、解析和知识点来源。',
    'assessment-rubric': '生成测验蓝图、评分标准、表现等级和证据要求。',
    'pbl-project': '生成真实情境、驱动问题、阶段任务、成果物、评价量规和教师支架。',
  };
  return `${specific[type]}${common}`;
}

function fallbackContent(
  type: CourseArtifactType,
  title: string,
  extractions: CourseMaterialExtraction[],
  reason: string,
) {
  const sourcePoints = extractions.flatMap((item) =>
    item.chunks.slice(0, 12).map((chunk) => ({
      materialId: item.materialId,
      page: chunk.page,
      text: chunk.text.replace(/\s+/g, ' ').slice(0, 260),
    })),
  );
  return [
    `# ${title}`,
    '',
    `> 自动降级说明：AI 服务暂不可用，系统已根据教师原始材料生成可审核草稿。原因：${reason}`,
    '',
    `## ${labels[type]}`,
    '',
    ...sourcePoints.flatMap((point, index) => [
      `### ${index + 1}. 来源要点`,
      `${point.text} [material:${point.materialId} page:${point.page}]`,
      '',
    ]),
    '## 教师审核提示',
    '请在发布前补充教学目标、活动设计和评价要求；所有结论应保留上述来源标记。',
  ].join('\n');
}

export async function runCourseArtifactJob(jobId: string, baseUrl: string) {
  const job = await updateCourseJob(jobId, { status: 'running', progress: 5, message: '读取课程材料' });
  try {
    const course = await readServerCourse(job.courseId);
    if (!course) throw new Error('课程不存在');
    const readyMaterials = course.materials.filter((item) => item.status === 'ready');
    if (readyMaterials.length === 0) throw new Error('没有已完成解析的课程材料');
    const extractions = (
      await Promise.all(readyMaterials.map((item) => readMaterialExtraction(item.id)))
    ).filter((item): item is CourseMaterialExtraction => Boolean(item));
    if (extractions.length === 0) throw new Error('课程材料缺少解析结果');
    const target = scopeTitle(job, course);
    const title = `${target}｜${labels[job.artifactType]}`;
    const citations = citationsFor(extractions, course);
    let artifact: CourseArtifactRecord;
    let degradationMessage: string | undefined;

    if (job.artifactType === 'lesson-courseware') {
      await updateCourseJob(jobId, { progress: 20, message: '调用 OpenMAIC 生成互动课件' });
      try {
        const generated = await generateClassroom(
          {
            requirement: `为“${target}”生成教学课件。${artifactInstruction(job.artifactType)}`,
            pdfContent: { text: sourceContext(extractions), images: [] },
            enableTTS: true,
            enableImageGeneration: true,
          },
          {
            baseUrl,
            onProgress: async (progress) => {
              await updateCourseJob(jobId, {
                progress: Math.min(90, Math.max(20, progress.progress)),
                message: progress.message,
              });
            },
          },
        );
        artifact = {
          id: nanoid(14), jobId, teacherId: job.teacherId, courseId: job.courseId,
          scope: job.scope, type: job.artifactType, title,
          content: `互动课件已生成，共 ${generated.scenesCount} 个场景。\n\n课堂地址：${generated.url}`,
          status: 'review', citations, classroomId: generated.id, classroomUrl: generated.url,
          createdAt: Date.now(), updatedAt: Date.now(),
        };
      } catch (error) {
        degradationMessage = error instanceof Error ? error.message : String(error);
        artifact = {
          id: nanoid(14), jobId, teacherId: job.teacherId, courseId: job.courseId,
          scope: job.scope, type: job.artifactType, title,
          content: fallbackContent(job.artifactType, title, extractions, degradationMessage),
          status: 'review', citations, reviewerNote: 'OpenMAIC 生成暂时失败，已自动降级为来源草稿。',
          createdAt: Date.now(), updatedAt: Date.now(),
        };
      }
    } else {
      await updateCourseJob(jobId, { progress: 25, message: `生成${labels[job.artifactType]}` });
      try {
        const { model, thinkingConfig } = await resolveModel({ stage: 'generate-classroom' });
        const result = await callLLM(
          {
            model,
            system: `你是教师端课程设计智能体。${artifactInstruction(job.artifactType)}`,
            prompt: `课程：${course.title}\n生成范围：${target}\n产物：${labels[job.artifactType]}\n\n教师材料：\n${sourceContext(extractions)}`,
          },
          'course-artifact-generation',
          undefined,
          thinkingConfig,
        );
        artifact = {
          id: nanoid(14), jobId, teacherId: job.teacherId, courseId: job.courseId,
          scope: job.scope, type: job.artifactType, title, content: result.text.trim(),
          status: 'review', citations, createdAt: Date.now(), updatedAt: Date.now(),
        };
      } catch (error) {
        degradationMessage = error instanceof Error ? error.message : String(error);
        artifact = {
          id: nanoid(14), jobId, teacherId: job.teacherId, courseId: job.courseId,
          scope: job.scope, type: job.artifactType, title,
          content: fallbackContent(job.artifactType, title, extractions, degradationMessage),
          status: 'review', citations, reviewerNote: 'AI 生成暂时失败，已自动降级为来源草稿。',
          createdAt: Date.now(), updatedAt: Date.now(),
        };
      }
    }
    artifact.htmlContent = markdownToArtifactHtml(artifact.content);
    if (WORD_ARTIFACT_TYPES.has(artifact.type)) {
      const wordFileName = `${artifact.title.replace(/[\\/:*?"<>|]/g, '_')}.docx`;
      const bytes = await buildCourseArtifactDocx(artifact.title, artifact.content);
      artifact.wordFileName = wordFileName;
      artifact.wordStorageKey = await saveCourseArtifactFile(artifact.id, wordFileName, bytes);
    }
    await saveCourseArtifact(artifact);
    await updateCourseJob(jobId, {
      status: 'review', progress: 100,
      message: degradationMessage ? '已自动降级为来源草稿，等待教师审核' : '生成完成，等待教师审核',
      artifactId: artifact.id,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    await updateCourseJob(jobId, { status: 'failed', progress: 100, message: '生成失败', error: message });
  }
}
