import type { GenerationSessionState } from '@/app/generation-preview/types';
import type { CourseArtifactJob, CourseMaterialExtraction, CourseSpace } from './types';
import { resolveCourseMinutes } from '@/lib/generation/course-duration';

type Scope = CourseArtifactJob['scope'];
const MAX_SOURCE_CHARACTERS = 60000;

export function coursewareScopeContext(course: CourseSpace, scope: Scope) {
  const courseModule = course.modules.find((item) =>
    scope.type === 'module'
      ? item.id === scope.moduleId
      : scope.type === 'lesson' && item.lessons.some((lesson) => lesson.id === scope.lessonId),
  );
  const lesson =
    scope.type === 'lesson'
      ? courseModule?.lessons.find((item) => item.id === scope.lessonId)
      : undefined;
  if ((scope.type === 'module' && !courseModule) || (scope.type === 'lesson' && !lesson)) {
    throw new Error('所选课时已不存在，请重新选择课时。');
  }
  return {
    title: lesson?.title || courseModule?.title || course.title,
    path: [course.title, courseModule?.title, lesson?.title].filter(Boolean).join(' / '),
    objectives: lesson?.objectives ?? courseModule?.objectives ?? [],
    lessonNotes: (lesson?.files ?? [])
      .filter(
        (file) =>
          file.status === 'ready' &&
          (file.type === 'lesson-objectives' || file.type === 'knowledge-points'),
      )
      .map((file) => `${file.title}\n${file.content}`)
      .join('\n\n'),
  };
}

/** Prefer this lesson's sources; never silently borrow sources from a different lesson. */
export function defaultCoursewareMaterialIds(course: CourseSpace, scope: Scope): string[] {
  coursewareScopeContext(course, scope);
  if (scope.type === 'course')
    return course.materials.filter((item) => item.status === 'ready').map((item) => item.id);
  const lessons = course.modules.flatMap((module) =>
    scope.type === 'module' && module.id !== scope.moduleId
      ? []
      : module.lessons.filter((lesson) => scope.type !== 'lesson' || lesson.id === scope.lessonId),
  );
  const linked = new Set(lessons.flatMap((lesson) => lesson.materialIds));
  const ready = course.materials.filter((item) => item.status === 'ready');
  const local = ready.filter((item) => linked.has(item.id));
  if (local.length) return local.map((item) => item.id);
  const assigned = new Set(
    course.modules.flatMap((module) => module.lessons.flatMap((lesson) => lesson.materialIds)),
  );
  const shared = ready.filter((item) => !assigned.has(item.id));
  // Multiple unassigned documents can cover unrelated topics; ask the teacher to choose.
  return shared.length === 1 ? [shared[0].id] : [];
}

export interface CoursewareGenerationOptions {
  materialIds: string[];
  targetDurationMinutes: string;
  instruction: string;
}

/** Both the lesson button and chat use this handoff into the existing outline-review flow. */
export async function createCoursewareGenerationSession(
  input: CoursewareGenerationOptions & {
    course: CourseSpace;
    scope: Scope;
    sessionId: string;
    userNickname?: string;
    userBio?: string;
  },
  readExtraction: (materialId: string) => Promise<CourseMaterialExtraction>,
): Promise<GenerationSessionState> {
  const { course, scope } = input;
  const context = coursewareScopeContext(course, scope);
  const targetDurationMinutes = resolveCourseMinutes(input.targetDurationMinutes);
  const materialIds = [...new Set(input.materialIds)];
  if (!materialIds.length) throw new Error('请选择至少一份已解析的课程资料。');
  const materials = materialIds.map((id) => {
    const material = course.materials.find((item) => item.id === id);
    if (!material || material.status !== 'ready') {
      throw new Error(`${material?.name || '所选资料'} 尚未解析完成或已被移除，请重新选择。`);
    }
    return material;
  });
  const sections = await Promise.all(
    materials.map(async (material) => {
      let extraction: CourseMaterialExtraction;
      try {
        extraction = await readExtraction(material.id);
      } catch {
        throw new Error(`读取“${material.name}”失败，请重试或重新解析该资料。`);
      }
      if (extraction.materialId !== material.id || !extraction.text?.trim()) {
        throw new Error(`“${material.name}”没有可用的解析正文，请重新解析该资料。`);
      }
      return `【${material.name}】\n${extraction.text.trim()}`;
    }),
  );
  const pdfText = sections.join('\n\n');
  if (pdfText.length > MAX_SOURCE_CHARACTERS) {
    throw new Error('所选资料正文合计超过 6 万字，请改选本课时需要的资料后重试。');
  }
  return {
    sessionId: input.sessionId,
    requirements: {
      targetDurationMinutes,
      requirement: [
        `请为“${context.title}”生成课时 PPT / 互动课件。`,
        `课程：${course.title}；当前课时范围：${context.path}。只围绕当前范围组织教学内容，不扩展为整门课程。`,
        context.objectives.length ? `【本次教学目标】\n${context.objectives.join('\n')}` : '',
        context.lessonNotes ? `【已审核的课时目标与知识点】\n${context.lessonNotes}` : '',
        `【教师选定的资料】\n${materials.map((item) => item.name).join('\n')}\n以本次选定的资料为依据，围绕当前课时选取相关内容。`,
        input.instruction.trim() ? `【教师补充要求】\n${input.instruction.trim()}` : '',
        '请先生成可供教师审阅的课件大纲，再根据确认的大纲制作课件。',
      ]
        .filter(Boolean)
        .join('\n\n'),
      userNickname: input.userNickname,
      userBio: input.userBio,
      webSearch: false,
      interactiveMode: false,
    },
    pdfText,
    pdfImages: [],
    imageStorageIds: [],
    currentStep: 'generating',
    previewPhase: 'preparing',
    courseSpaceContext: { courseId: course.id, scope, materialIds },
  };
}
