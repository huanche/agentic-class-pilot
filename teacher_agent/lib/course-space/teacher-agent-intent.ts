import type {
  CourseArtifactJob,
  CourseArtifactType,
  CourseLessonFileType,
  CourseSpace,
} from './types';

export type TeacherWorkspaceAction =
  | {
      type: 'generate-artifact';
      artifactType: CourseArtifactType;
      label: string;
      scope?: CourseArtifactJob['scope'];
      instruction?: string;
    }
  | { type: 'reorder-lesson'; lessonId: string; beforeLessonId: string; label: string }
  | { type: 'create-lessons'; moduleId: string; start: number; end: number; label: string }
  | {
      type: 'create-lesson-files';
      lessonIds: string[];
      fileTypes: CourseLessonFileType[];
      label: string;
      populateContent?: boolean;
      instruction?: string;
    }
  | { type: 'move-artifacts'; fromLessonId: string; toLessonId: string; label: string }
  | { type: 'delete-artifact'; artifactTitle: string; label: string }
  | { type: 'delete-lesson'; lessonId: string; cascade: boolean; label: string };

export type TeacherOperationPlan = {
  id: string;
  kind:
    | 'inspect-exercises'
    | 'generate-artifact'
    | 'reorder-lesson'
    | 'create-lessons'
    | 'create-lesson-files'
    | 'move-artifacts'
    | 'delete-artifact'
    | 'delete-lesson'
    | 'compare-artifacts'
    | 'adapt-next-lesson';
  title: string;
  summary: string;
  requiresConfirmation: boolean;
  status: 'planned' | 'completed' | 'blocked';
  steps: Array<{
    id: string;
    tool:
      | 'course.inspect'
      | 'artifact.workflow'
      | 'course.reorder'
      | 'course.structure'
      | 'course.move'
      | 'course.delete'
      | 'artifact.compare'
      | 'analytics.read';
    label: string;
    status: 'pending' | 'completed' | 'blocked';
  }>;
  action?: TeacherWorkspaceAction;
  result?: string;
};

const artifactRules: Array<{ artifactType: CourseArtifactType; label: string; pattern: RegExp }> = [
  { artifactType: 'course-outline', label: '课程教学大纲', pattern: /(?:课程|教学)?大纲/iu },
  {
    artifactType: 'module-plan',
    label: '模块教学计划',
    pattern: /(?:模块|课程|教学)?(?:计划|教案)/u,
  },
  {
    artifactType: 'lesson-courseware',
    label: '课时 PPT / 互动课件',
    pattern: /互动课件|课件|幻灯片|PPT/iu,
  },
  { artifactType: 'narration', label: '讲稿与配音', pattern: /讲稿|配音|旁白|解说词/u },
  {
    artifactType: 'exercise-set',
    label: '习题与答案',
    pattern: /诊断题|习题|练习题|题库|参考答案|答案解析|出题/u,
  },
  {
    artifactType: 'assessment-rubric',
    label: '测验与评分量规',
    pattern: /评分量规|评价量规|评分标准|测验|考核方案/u,
  },
  { artifactType: 'pbl-project', label: 'PBL 项目', pattern: /PBL|项目式学习/iu },
];

const creationPattern =
  /生成|制作|创建|编写|撰写|产出|设计|修改|完善|补充|重写|润色|整理(?:一份|成)|准备一份|来一份|出(?:一份|一套|\d+道)?|帮我|替我|我(?:想要|需要)|需要一份/u;
const discussionPattern =
  /^(?:如何|怎么|为什么)(?:才能|可以|进行|使用)?.{0,12}(?:生成|制作|创建|编写)|(?:生成|制作|创建|编写).{0,8}(?:方法|流程|功能|步骤)(?:是什么|有哪些|吗|呢)?[？?]?$/u;

/** Routes artifact creation requests into the audited workflow instead of chat. */
export function detectTeacherWorkspaceAction(
  content: string,
): Extract<TeacherWorkspaceAction, { type: 'generate-artifact' }> | undefined {
  const normalized = content.replace(/\s+/g, ' ').trim();
  const artifact = artifactRules.find((rule) => rule.pattern.test(normalized));
  if (!artifact) return undefined;

  const explicitCreation =
    creationPattern.test(normalized) || /(?:给|为).{0,20}(?:出题|做|写|准备)/u.test(normalized);
  if (!explicitCreation || discussionPattern.test(normalized)) return undefined;

  return { type: 'generate-artifact', artifactType: artifact.artifactType, label: artifact.label };
}

const numeral: Record<string, number> = {
  一: 1,
  二: 2,
  三: 3,
  四: 4,
  五: 5,
  六: 6,
  七: 7,
  八: 8,
  九: 9,
  十: 10,
};
function ordinal(value?: string) {
  if (!value) return undefined;
  if (/^\d+$/.test(value)) return Number(value);
  if (value === '十') return 10;
  if (value.startsWith('十')) return 10 + (numeral[value[1]] || 0);
  if (value.endsWith('十')) return (numeral[value[0]] || 0) * 10;
  if (value.includes('十')) return (numeral[value[0]] || 0) * 10 + (numeral[value[2]] || 0);
  return numeral[value];
}

function findLessonByOrdinal(course: CourseSpace, value?: string) {
  const target = ordinal(value);
  if (!target) return undefined;
  const lessons = course.modules.flatMap((module) =>
    module.lessons.map((lesson) => ({ module, lesson })),
  );
  return (
    lessons.find(
      ({ lesson }) =>
        ordinal(lesson.title.match(/第([一二三四五六七八九十\d]+)(?:周|课时)/u)?.[1]) === target,
    ) ?? lessons.sort((a, b) => a.lesson.order - b.lesson.order)[target - 1]
  );
}

/** Converts natural language into a reviewable plan before any workflow or mutation runs. */
export function planTeacherWorkspaceOperation(
  content: string,
  course: CourseSpace,
  currentScope?: CourseArtifactJob['scope'],
): TeacherOperationPlan | undefined {
  const normalized = content.replace(/\s+/g, ' ').trim();
  const id = `plan-${Date.now().toString(36)}`;
  const moduleOrdinal = ordinal(normalized.match(/第([一二三四五六七八九十\d]+)(?:章|模块)/u)?.[1]);
  const targetModule = moduleOrdinal
    ? [...course.modules].sort((a, b) => a.order - b.order)[moduleOrdinal - 1]
    : undefined;

  const lessonFileRules: Array<{ type: CourseLessonFileType; label: string; pattern: RegExp }> = [
    { type: 'lesson-objectives', label: '课时目标', pattern: /课时目标|课程目标|学习目标/u },
    { type: 'knowledge-points', label: '知识点', pattern: /知识点/u },
    { type: 'teaching-activities', label: '教学活动', pattern: /教学活动/u },
    { type: 'courseware-pages', label: '课件页面', pattern: /课件页面/u },
    { type: 'narration-segments', label: '讲稿片段', pattern: /讲稿片段/u },
    { type: 'exercises', label: '习题', pattern: /习题/u },
    { type: 'assessment-criteria', label: '评价指标', pattern: /评价指标/u },
  ];
  const requestedLessonFiles = lessonFileRules.filter((rule) => rule.pattern.test(normalized));
  const lessonFileRange = normalized.match(
    /(?:第)?(\d{1,2})\s*周?\s*(?:-|—|–|至|到)\s*(?:第)?(\d{1,2})\s*周/u,
  );
  if (
    requestedLessonFiles.length &&
    /(?:创建|建立|添加|生成).{0,20}(?:文件|课时目标|课程目标|学习目标|知识点|教学活动)|(?:文件夹下|课时下).{0,20}(?:创建|建立|添加|生成)/u.test(
      normalized,
    )
  ) {
    const start = lessonFileRange
      ? Number(lessonFileRange[1])
      : ordinal(normalized.match(/第([一二三四五六七八九十\d]+)周/u)?.[1]);
    const end = lessonFileRange ? Number(lessonFileRange[2]) : start;
    const populateContent =
      /生成|具体内容|根据课程材料|完善|填写|写入/u.test(normalized) &&
      !/(?:创建|建立|添加)(?:空白|空的?|结构化)?(?:文件|文件夹|目录)/u.test(normalized);
    const scopedLessonId = !start && currentScope?.type === 'lesson' ? currentScope.lessonId : undefined;
    const targets = course.modules
      .flatMap((module) => module.lessons)
      .filter((lesson) => {
        if (scopedLessonId) return lesson.id === scopedLessonId;
        const week = ordinal(lesson.title.match(/^第([一二三四五六七八九十\d]+)周$/u)?.[1]);
        return week && start && end && week >= start && week <= end;
      });
    if (targets.length)
      return {
        id,
        kind: 'create-lesson-files',
        title: `创建${requestedLessonFiles.map((item) => item.label).join('、')}文件`,
        summary: populateContent
          ? `将依据课程材料，为${targets[0].title}至${targets[targets.length - 1].title}生成 ${requestedLessonFiles.length} 类教学内容；已有同类型文件将更新正文。`
          : `将在${targets[0].title}至${targets[targets.length - 1].title}的 ${targets.length} 个课时文件夹中分别创建 ${requestedLessonFiles.length} 类结构化文件；已有同类型文件将保留。`,
        requiresConfirmation: !populateContent,
        status: 'planned',
        action: {
          type: 'create-lesson-files',
          lessonIds: targets.map((lesson) => lesson.id),
          fileTypes: requestedLessonFiles.map((item) => item.type),
          label: '批量创建课时结构文件',
          populateContent,
          instruction: normalized,
        },
        steps: [
          {
            id: 'validate',
            tool: 'course.inspect',
            label: '校验课时范围与文件类型',
            status: 'pending',
          },
          {
            id: 'create',
            tool: 'course.structure',
            label: '创建并持久化课时结构文件',
            status: 'pending',
          },
        ],
      };
  }

  const moveContents = normalized.match(
    /(?:把|将)?第([一二三四五六七八九十\d]+)(?:周|课时)(?:里面|以内|内|下面|下)?(?:的)?(?:全部|所有)?(?:内容|文件|产物).{0,10}(?:移到|移动到|转移到|挪到)第([一二三四五六七八九十\d]+)(?:周|课时)/u,
  );
  if (moveContents) {
    const source = findLessonByOrdinal(course, moveContents[1]);
    const target = findLessonByOrdinal(course, moveContents[2]);
    if (source && target && source.lesson.id !== target.lesson.id)
      return {
        id,
        kind: 'move-artifacts',
        title: '移动课时文件',
        summary: `将“${source.lesson.title}”中的结构文件与教学产物全部移动到“${target.lesson.title}”。课程结构和来源引用保持不变；同类型文件冲突时将安全阻止。`,
        requiresConfirmation: true,
        status: 'planned',
        action: {
          type: 'move-artifacts',
          fromLessonId: source.lesson.id,
          toLessonId: target.lesson.id,
          label: '移动课时全部产物',
        },
        steps: [
          {
            id: 'validate',
            tool: 'course.inspect',
            label: '校验源课时、目标课时和待移动产物',
            status: 'pending',
          },
          { id: 'move', tool: 'course.move', label: '更新产物所属课时并持久化', status: 'pending' },
        ],
      };
  }

  const deleteLesson = normalized.match(
    /(?:删除|移除)第([一二三四五六七八九十\d]+)(?:周|课时)(?:文件夹)?/u,
  );
  if (deleteLesson) {
    const target = findLessonByOrdinal(course, deleteLesson[1]);
    if (target) {
      const cascade =
        /(?:连同|包括|包含|以及|和).{0,8}(?:里面|其中|课时)?(?:的)?(?:内容|文件|产物)|级联删除|全部删除/u.test(
          normalized,
        );
      return {
        id,
        kind: 'delete-lesson',
        title: `删除“${target.lesson.title}”文件夹`,
        summary: cascade
          ? '将删除该课时及其全部课程产物；此操作不可在工作区内直接撤销。'
          : '仅删除空课时文件夹；如其中仍有产物，执行器将安全阻止本次操作。',
        requiresConfirmation: true,
        status: 'planned',
        action: {
          type: 'delete-lesson',
          lessonId: target.lesson.id,
          cascade,
          label: cascade ? '级联删除课时及产物' : '删除空课时文件夹',
        },
        steps: [
          {
            id: 'validate',
            tool: 'course.inspect',
            label: '检查课时及关联产物',
            status: 'pending',
          },
          {
            id: 'delete',
            tool: 'course.delete',
            label: cascade ? '删除关联产物与课时文件夹' : '删除空课时文件夹',
            status: 'pending',
          },
        ],
      };
    }
  }

  const deleteArtifact = normalized.match(/(?:删除|移除)(?:产物|文件)?[“"]([^”"]+)[”"]/u);
  if (deleteArtifact) {
    const artifactTitle = deleteArtifact[1].trim();
    return {
      id,
      kind: 'delete-artifact',
      title: `删除产物“${artifactTitle}”`,
      summary: '将按完整标题定位当前课程中的产物，确认唯一匹配后删除产物记录与其存储文件。',
      requiresConfirmation: true,
      status: 'planned',
      action: { type: 'delete-artifact', artifactTitle, label: '删除课程产物' },
      steps: [
        { id: 'validate', tool: 'course.inspect', label: '按标题校验唯一产物', status: 'pending' },
        { id: 'delete', tool: 'course.delete', label: '删除产物记录与存储文件', status: 'pending' },
      ],
    };
  }

  const weekRange = normalized.match(
    /(?:第)?(\d{1,2})\s*周?\s*(?:-|—|–|至|到)\s*(?:第)?(\d{1,2})\s*周/u,
  );
  if (
    weekRange &&
    /(?:创建|建立|添加|生成|安排|规划).{0,16}(?:周|课时|文件夹)|(?:周|课时|文件夹).{0,16}(?:创建|建立|添加|生成|安排|规划)/u.test(
      normalized,
    )
  ) {
    const start = Number(weekRange[1]);
    const end = Number(weekRange[2]);
    const namedModule = course.modules.find((module) => normalized.includes(module.title));
    const destination =
      namedModule ??
      targetModule ??
      (/课件/u.test(normalized)
        ? course.modules.find((module) => /课件/u.test(module.title))
        : undefined) ??
      course.modules[0];
    if (destination && start >= 1 && end >= start && end - start <= 52) {
      return {
        id,
        kind: 'create-lessons',
        title: `创建第${start}—${end}周课时文件夹`,
        summary: `将在“${destination.title}”模块下建立 ${end - start + 1} 个周次课时文件夹；已存在的同名课时将保留。`,
        requiresConfirmation: true,
        status: 'planned',
        action: {
          type: 'create-lessons',
          moduleId: destination.id,
          start,
          end,
          label: '批量创建课时文件夹',
        },
        steps: [
          {
            id: 'validate',
            tool: 'course.inspect',
            label: '校验目标模块与周次范围',
            status: 'pending',
          },
          {
            id: 'create',
            tool: 'course.structure',
            label: '批量创建并持久化课时文件夹',
            status: 'pending',
          },
        ],
      };
    }
  }

  if (/检查|核查|审查/u.test(normalized) && /练习|习题/u.test(normalized) && targetModule) {
    return {
      id,
      kind: 'inspect-exercises',
      title: `检查“${targetModule.title}”练习覆盖`,
      summary: '读取模块课时与已生成习题，逐项检查缺口。',
      requiresConfirmation: false,
      status: 'planned',
      steps: [
        {
          id: 'inspect',
          tool: 'course.inspect',
          label: '读取模块、课时和习题产物',
          status: 'pending',
        },
      ],
    };
  }
  const reorder = normalized.match(
    /第([一二三四五六七八九十\d]+)课时.{0,12}(?:调整|移动|排).{0,8}第([一二三四五六七八九十\d]+)课时之前/u,
  );
  if (reorder) {
    const lessons = course.modules.flatMap((module) =>
      [...module.lessons].sort((a, b) => a.order - b.order),
    );
    const from = lessons[(ordinal(reorder[1]) || 0) - 1];
    const before = lessons[(ordinal(reorder[2]) || 0) - 1];
    if (from && before)
      return {
        id,
        kind: 'reorder-lesson',
        title: '调整课时顺序',
        summary: `将“${from.title}”移动到“${before.title}”之前，并重新编号。`,
        requiresConfirmation: true,
        status: 'planned',
        action: {
          type: 'reorder-lesson',
          lessonId: from.id,
          beforeLessonId: before.id,
          label: '调整课时顺序',
        },
        steps: [
          {
            id: 'validate',
            tool: 'course.inspect',
            label: '校验课时与所属模块',
            status: 'pending',
          },
          {
            id: 'reorder',
            tool: 'course.reorder',
            label: '更新课程结构并持久化',
            status: 'pending',
          },
        ],
      };
  }
  if (
    /检查|核查|对比|比较/u.test(normalized) &&
    /课件/u.test(normalized) &&
    /讲稿|旁白/u.test(normalized) &&
    /冲突|一致/u.test(normalized)
  ) {
    return {
      id,
      kind: 'compare-artifacts',
      title: '检查课件与讲稿一致性',
      summary: '调用产物检查流程，对齐最新课件与讲稿并报告缺失或潜在冲突。',
      requiresConfirmation: false,
      status: 'planned',
      steps: [
        {
          id: 'compare',
          tool: 'artifact.compare',
          label: '读取并比较最新课件与讲稿',
          status: 'pending',
        },
      ],
    };
  }
  if (
    /学生.{0,8}(?:错误率|错题|学情).{0,20}(?:修改|调整|优化).{0,12}(?:下一|下节)/u.test(normalized)
  ) {
    return {
      id,
      kind: 'adapt-next-lesson',
      title: '依据学情调整下一课时',
      summary: '读取学生错误率，再形成课时修订建议。',
      requiresConfirmation: false,
      status: 'planned',
      steps: [
        {
          id: 'analytics',
          tool: 'analytics.read',
          label: '读取学生错误率与题目映射',
          status: 'pending',
        },
        { id: 'adapt', tool: 'course.inspect', label: '生成下一课时调整建议', status: 'pending' },
      ],
    };
  }
  const action = detectTeacherWorkspaceAction(normalized);
  if (!action) return undefined;
  const requestedLesson = findLessonByOrdinal(
    course,
    normalized.match(/第([一二三四五六七八九十\d]+)(?:周|课时)/u)?.[1],
  );
  action.scope = requestedLesson
    ? { type: 'lesson', lessonId: requestedLesson.lesson.id }
    : targetModule
      ? { type: 'module', moduleId: targetModule.id }
      : currentScope ?? { type: 'course' };
  action.instruction = normalized;
  const scopeTitle = requestedLesson?.lesson.title ?? targetModule?.title;
  return {
    id,
    kind: 'generate-artifact',
    title: `生成${action.label}`,
    summary: `${scopeTitle ? `范围：${scopeTitle}；` : ''}进入标准生成—审核—发布工作流。`,
    requiresConfirmation: false,
    status: 'planned',
    action,
    steps: [
      {
        id: 'context',
        tool: 'course.inspect',
        label: '装载课程材料、图谱与范围',
        status: 'pending',
      },
      {
        id: 'generate',
        tool: 'artifact.workflow',
        label: `调用${action.label}标准工作流`,
        status: 'pending',
      },
    ],
  };
}
