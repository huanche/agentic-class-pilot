import type { TeacherOperationPlan } from '@/lib/course-space/teacher-agent-intent';
import { callLLM } from '@/lib/ai/llm';
import { resolveModel } from '@/lib/server/resolve-model';
import {
  deleteCourseArtifact,
  listCourseArtifacts,
  readServerCourse,
  readMaterialExtraction,
  saveCourseArtifact,
  updateServerCourse,
} from './course-space-storage';

const lessonFileTitles = {
  'lesson-objectives': '课时目标',
  'knowledge-points': '知识点',
  'teaching-activities': '教学活动',
  'courseware-pages': '课件页面',
  'narration-segments': '讲稿片段',
  exercises: '习题',
  'assessment-criteria': '评价指标',
} as const;

export async function generateLessonFileContent(
  course: NonNullable<Awaited<ReturnType<typeof readServerCourse>>>,
  lessonTitle: string,
  fileTypes: Array<keyof typeof lessonFileTitles>,
  instruction?: string,
) {
  const extractions = (
    await Promise.all(course.materials.map((material) => readMaterialExtraction(material.id)))
  ).filter((item): item is NonNullable<typeof item> => Boolean(item));
  const sources = extractions
    .flatMap((item) =>
      item.chunks
        .slice(0, 30)
        .map(
          (chunk) =>
            `[material:${item.materialId} page:${chunk.page}] ${chunk.text.replace(/\s+/g, ' ')}`,
        ),
    )
    .join('\n')
    .slice(0, 30000);
  const { model, thinkingConfig } = await resolveModel({ stage: 'generate-classroom' });
  const result = await callLLM(
    {
      model,
      system:
        '你是课程工程智能体。请严格依据教师材料生成可直接写入课程文件的内容，关键结论保留材料页码引用。只输出合法 JSON 对象，不要使用代码围栏。',
      prompt: `课程：${course.title}\n课时：${lessonTitle}\n教师要求：${instruction || '生成课时结构内容'}\n需要字段：${fileTypes.join(', ')}\nJSON 键必须使用上述英文类型，值为 Markdown 字符串。\n\n教师材料：\n${sources || '暂无可解析材料，请依据已有课程结构形成待教师审核的草稿。'}`,
    },
    'lesson-file-content-generation',
    { retries: 1 },
    thinkingConfig,
  );
  const raw = result.text
    .trim()
    .replace(/^```(?:json)?\s*/i, '')
    .replace(/\s*```$/, '');
  return JSON.parse(raw) as Partial<Record<keyof typeof lessonFileTitles, string>>;
}

export async function executeReadOnlyTeacherPlan(
  courseId: string,
  plan: TeacherOperationPlan,
): Promise<TeacherOperationPlan> {
  const course = await readServerCourse(courseId);
  if (!course) throw new Error('课程不存在');
  const artifacts = await listCourseArtifacts(courseId);
  if (plan.kind === 'inspect-exercises') {
    const courseModule = course.modules.find((item) => plan.title.includes(item.title));
    if (!courseModule)
      return {
        ...plan,
        status: 'blocked',
        result: '未能解析目标模块，请在指令中明确模块名称或序号。',
        steps: plan.steps.map((step) => ({ ...step, status: 'blocked' })),
      };
    const exercises = artifacts.filter((item) => {
      if (item.type !== 'exercise-set') return false;
      const scope = item.scope;
      return (
        scope.type === 'course' ||
        (scope.type === 'module' && scope.moduleId === courseModule.id) ||
        (scope.type === 'lesson' && courseModule.lessons.some((lesson) => lesson.id === scope.lessonId))
      );
    });
    const coveredLessons = new Set(
      exercises.flatMap((item) =>
        item.scope.type === 'lesson'
          ? [item.scope.lessonId]
          : courseModule.lessons.map((lesson) => lesson.id),
      ),
    );
    const missing = courseModule.lessons.filter((lesson) => !coveredLessons.has(lesson.id));
    const result =
      exercises.length === 0
        ? `“${courseModule.title}”包含 ${courseModule.lessons.length} 个课时，目前没有关联的习题产物，建议按模块或逐课时生成练习。`
        : missing.length
          ? `找到 ${exercises.length} 份习题产物；仍缺少：${missing.map((item) => item.title).join('、')}。`
          : `找到 ${exercises.length} 份习题产物，${courseModule.lessons.length} 个课时均已有练习覆盖。`;
    return {
      ...plan,
      status: 'completed',
      result,
      steps: plan.steps.map((step) => ({ ...step, status: 'completed' })),
    };
  }
  if (plan.kind === 'compare-artifacts') {
    const courseware = artifacts
      .filter((item) => item.type === 'lesson-courseware')
      .sort((a, b) => b.updatedAt - a.updatedAt)[0];
    const narration = artifacts
      .filter((item) => item.type === 'narration')
      .sort((a, b) => b.updatedAt - a.updatedAt)[0];
    const missing = [!courseware && '课件', !narration && '讲稿'].filter(Boolean).join('和');
    const unavailable = !missing && (!courseware.content.trim() || !narration.content.trim());
    const result = missing
      ? `无法开始一致性检查：尚缺少${missing}。请先通过标准产物工作流生成并审核。`
      : unavailable
        ? '已找到课件和讲稿记录，但其中一项没有可比较的文本内容；请先完成可检索文本提取。'
        : `已完成输入校验：最新课件“${courseware.title}”与讲稿“${narration.title}”均具备可比较文本，可交由后续语义冲突检查器处理。`;
    const blocked = Boolean(missing || unavailable);
    return {
      ...plan,
      status: blocked ? 'blocked' : 'completed',
      result,
      steps: plan.steps.map((step) => ({ ...step, status: blocked ? 'blocked' : 'completed' })),
    };
  }
  if (plan.kind === 'adapt-next-lesson') {
    return {
      ...plan,
      status: 'blocked',
      result:
        '当前课程尚未接入标准化学生错误率数据源。为避免伪造学情，本操作已暂停；接入学生作答统计 API 后可继续执行。',
      steps: plan.steps.map((step, index) => ({
        ...step,
        status: index === 0 ? 'blocked' : 'pending',
      })),
    };
  }
  return plan;
}

export async function executeConfirmedTeacherPlan(
  courseId: string,
  plan: TeacherOperationPlan,
): Promise<{ plan: TeacherOperationPlan; dispatch?: 'artifact-workflow' }> {
  if (plan.kind === 'generate-artifact' && plan.action?.type === 'generate-artifact') {
    return {
      plan: {
        ...plan,
        status: 'completed',
        steps: plan.steps.map((step) => ({ ...step, status: 'completed' })),
      },
      dispatch: 'artifact-workflow',
    };
  }
  if (plan.kind === 'create-lessons' && plan.action?.type === 'create-lessons') {
    const { moduleId, start, end } = plan.action;
    let created = 0;
    await updateServerCourse(courseId, (course) => {
      const target = course.modules.find((module) => module.id === moduleId);
      if (!target) throw new Error('目标模块已不存在，请重新生成操作计划');
      const existing = new Set(target.lessons.map((lesson) => lesson.title));
      const now = Date.now();
      const additions = Array.from({ length: end - start + 1 }, (_, index) => start + index)
        .map((week) => `第${week}周`)
        .filter((title) => !existing.has(title))
        .map((title, index) => ({
          id: `lesson_${now.toString(36)}_${index}`,
          moduleId,
          title,
          order: target.lessons.length + index + 1,
          objectives: [],
          materialIds: [],
          createdAt: now,
          updatedAt: now,
        }));
      created = additions.length;
      return {
        ...course,
        modules: course.modules.map((module) =>
          module.id === moduleId
            ? { ...module, lessons: [...module.lessons, ...additions], updatedAt: now }
            : module,
        ),
      };
    });
    return {
      plan: {
        ...plan,
        status: 'completed',
        result: `已创建 ${created} 个课时文件夹；同名周次已自动跳过。`,
        steps: plan.steps.map((step) => ({ ...step, status: 'completed' })),
      },
    };
  }
  if (plan.kind === 'create-lesson-files' && plan.action?.type === 'create-lesson-files') {
    const action = plan.action;
    let created = 0;
    let populated = 0;
    const currentCourse = await readServerCourse(courseId);
    if (!currentCourse) throw new Error('课程不存在');
    const generatedByLesson = new Map<
      string,
      Partial<Record<keyof typeof lessonFileTitles, string>>
    >();
    if (action.populateContent) {
      for (const lesson of currentCourse.modules.flatMap((module) => module.lessons)) {
        if (!action.lessonIds.includes(lesson.id)) continue;
        generatedByLesson.set(
          lesson.id,
          await generateLessonFileContent(
            currentCourse,
            lesson.title,
            action.fileTypes,
            action.instruction,
          ),
        );
      }
    }
    await updateServerCourse(courseId, (course) => {
      const knownLessons = new Set(
        course.modules.flatMap((module) => module.lessons.map((lesson) => lesson.id)),
      );
      if (action.lessonIds.some((id) => !knownLessons.has(id)))
        throw new Error('部分目标课时已变化，请重新生成操作计划');
      const now = Date.now();
      return {
        ...course,
        updatedAt: now,
        modules: course.modules.map((module) => ({
          ...module,
          lessons: module.lessons.map((lesson) => {
            if (!action.lessonIds.includes(lesson.id)) return lesson;
            const existing = new Set((lesson.files ?? []).map((file) => file.type));
            const generated = generatedByLesson.get(lesson.id) ?? {};
            const additions = action.fileTypes
              .filter((type) => !existing.has(type))
              .map((type, index) => ({
                id: `lesson_file_${now.toString(36)}_${lesson.id}_${index}`,
                lessonId: lesson.id,
                type,
                title: lessonFileTitles[type],
                content: generated[type]?.trim() || '',
                status: generated[type]?.trim() ? ('ready' as const) : ('draft' as const),
                createdAt: now,
                updatedAt: now,
              }));
            created += additions.length;
            const updatedFiles = (lesson.files ?? []).map((file) => {
              const content = generated[file.type]?.trim();
              if (!content || !action.fileTypes.includes(file.type)) return file;
              populated += 1;
              return { ...file, content, status: 'ready' as const, updatedAt: now };
            });
            populated += additions.filter((file) => file.content).length;
            return { ...lesson, updatedAt: now, files: [...updatedFiles, ...additions] };
          }),
        })),
      };
    });
    return {
      plan: {
        ...plan,
        status: 'completed',
        result: action.populateContent
          ? `已创建 ${created} 个课时结构文件，并写入或更新 ${populated} 个文件的具体内容。`
          : `已创建 ${created} 个课时结构文件；已有同类型文件已自动跳过。`,
        steps: plan.steps.map((step) => ({ ...step, status: 'completed' })),
      },
    };
  }
  if (plan.kind === 'move-artifacts' && plan.action?.type === 'move-artifacts') {
    const action = plan.action;
    const course = await readServerCourse(courseId);
    if (!course) throw new Error('课程不存在');
    const lessons = course.modules.flatMap((module) => module.lessons);
    const source = lessons.find((lesson) => lesson.id === action.fromLessonId);
    const target = lessons.find((lesson) => lesson.id === action.toLessonId);
    if (!source || !target) throw new Error('源课时或目标课时已变化，请重新生成操作计划');
    const sourceFiles = source.files ?? [];
    const targetFileTypes = new Set((target.files ?? []).map((file) => file.type));
    const conflicts = sourceFiles.filter((file) => targetFileTypes.has(file.type));
    if (conflicts.length)
      throw new Error(
        `目标课时已有${conflicts.map((file) => `“${file.title}”`).join('、')}，请先处理同类型文件，避免覆盖`,
      );
    const artifacts = (await listCourseArtifacts(courseId)).filter(
      (artifact) => artifact.scope.type === 'lesson' && artifact.scope.lessonId === source.id,
    );
    if (!artifacts.length && !sourceFiles.length)
      throw new Error(`“${source.title}”中没有可移动的课程文件`);
    const now = Date.now();
    if (sourceFiles.length)
      await updateServerCourse(courseId, (current) => ({
        ...current,
        updatedAt: now,
        modules: current.modules.map((module) => ({
          ...module,
          lessons: module.lessons.map((lesson) =>
            lesson.id === source.id
              ? { ...lesson, files: [], updatedAt: now }
              : lesson.id === target.id
                ? {
                    ...lesson,
                    files: [
                      ...(lesson.files ?? []),
                      ...sourceFiles.map((file) => ({
                        ...file,
                        lessonId: target.id,
                        updatedAt: now,
                      })),
                    ],
                    updatedAt: now,
                  }
                : lesson,
          ),
        })),
      }));
    await Promise.all(
      artifacts.map((artifact) =>
        saveCourseArtifact({
          ...artifact,
          scope: { type: 'lesson', lessonId: target.id },
          updatedAt: now,
        }),
      ),
    );
    return {
      plan: {
        ...plan,
        status: 'completed',
        result: `已将 ${sourceFiles.length} 个结构文件和 ${artifacts.length} 个教学产物从“${source.title}”移动到“${target.title}”。`,
        steps: plan.steps.map((step) => ({ ...step, status: 'completed' })),
      },
    };
  }
  if (plan.kind === 'delete-artifact' && plan.action?.type === 'delete-artifact') {
    const action = plan.action;
    const artifacts = await listCourseArtifacts(courseId);
    const exact = artifacts.filter(
      (artifact) => artifact.title.trim() === action.artifactTitle.trim(),
    );
    const matches = exact.length
      ? exact
      : artifacts.filter((artifact) => artifact.title.includes(action.artifactTitle));
    if (!matches.length) throw new Error(`未找到产物“${action.artifactTitle}”`);
    if (matches.length > 1)
      throw new Error(`找到 ${matches.length} 个同名或近似产物，请使用更完整的标题后重试`);
    await deleteCourseArtifact(matches[0].id);
    return {
      plan: {
        ...plan,
        status: 'completed',
        result: `已删除产物“${matches[0].title}”。`,
        steps: plan.steps.map((step) => ({ ...step, status: 'completed' })),
      },
    };
  }
  if (plan.kind === 'delete-lesson' && plan.action?.type === 'delete-lesson') {
    const action = plan.action;
    const course = await readServerCourse(courseId);
    if (!course) throw new Error('课程不存在');
    const target = course.modules
      .flatMap((module) => module.lessons.map((lesson) => ({ module, lesson })))
      .find((item) => item.lesson.id === action.lessonId);
    if (!target) throw new Error('目标课时已不存在，请重新生成操作计划');
    const artifacts = (await listCourseArtifacts(courseId)).filter(
      (artifact) =>
        artifact.scope.type === 'lesson' && artifact.scope.lessonId === target.lesson.id,
    );
    const structureFileCount = target.lesson.files?.length ?? 0;
    if ((artifacts.length || structureFileCount) && !action.cascade)
      throw new Error(
        `“${target.lesson.title}”仍包含 ${structureFileCount} 个结构文件和 ${artifacts.length} 个教学产物。请先移动内容，或明确要求“连同内容一起删除”`,
      );
    if (action.cascade)
      await Promise.all(artifacts.map((artifact) => deleteCourseArtifact(artifact.id)));
    await updateServerCourse(courseId, (current) => ({
      ...current,
      modules: current.modules.map((module) =>
        module.id === target.module.id
          ? {
              ...module,
              updatedAt: Date.now(),
              lessons: module.lessons
                .filter((lesson) => lesson.id !== target.lesson.id)
                .map((lesson, order) => ({ ...lesson, order })),
            }
          : module,
      ),
    }));
    return {
      plan: {
        ...plan,
        status: 'completed',
        result:
          artifacts.length || structureFileCount
            ? `已删除“${target.lesson.title}”及其 ${structureFileCount} 个结构文件、${artifacts.length} 个教学产物。`
            : `已删除空课时文件夹“${target.lesson.title}”。`,
        steps: plan.steps.map((step) => ({ ...step, status: 'completed' })),
      },
    };
  }
  if (plan.kind !== 'reorder-lesson' || plan.action?.type !== 'reorder-lesson')
    throw new Error('不支持的课程操作');
  const { lessonId, beforeLessonId } = plan.action;
  await updateServerCourse(courseId, (course) => {
    const lessons = course.modules.flatMap((module) =>
      module.lessons.map((lesson) => ({ lesson, module })),
    );
    const source = lessons.find((item) => item.lesson.id === lessonId);
    const target = lessons.find((item) => item.lesson.id === beforeLessonId);
    if (!source || !target) throw new Error('课时已变化，请重新生成操作计划');
    if (source.module.id !== target.module.id) throw new Error('首版仅支持同一模块内调整课时顺序');
    const ordered = [...source.module.lessons]
      .sort((a, b) => a.order - b.order)
      .filter((item) => item.id !== lessonId);
    ordered.splice(
      ordered.findIndex((item) => item.id === beforeLessonId),
      0,
      source.lesson,
    );
    const now = Date.now();
    const modules = course.modules.map((module) =>
      module.id === source.module.id
        ? {
            ...module,
            updatedAt: now,
            lessons: ordered.map((lesson, order) => ({ ...lesson, order, updatedAt: now })),
          }
        : module,
    );
    return { ...course, modules };
  });
  return {
    plan: {
      ...plan,
      status: 'completed',
      result: '课时顺序已更新并保存。',
      steps: plan.steps.map((step) => ({ ...step, status: 'completed' })),
    },
  };
}
