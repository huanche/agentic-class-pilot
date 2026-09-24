export type CoursewareConversionMode = 'faithful' | 'learning-skills-enhanced';

export type CoursewareSourceKind = 'pptx' | 'pdf' | 'document';

export function isCoursewareConversionFile(file: { name: string; type?: string }): boolean {
  const name = file.name.trim().toLowerCase();
  const type = file.type?.trim().toLowerCase() || '';
  return (
    name.endsWith('.pptx') ||
    name.endsWith('.ppt') ||
    name.endsWith('.pdf') ||
    type === 'application/pdf' ||
    type === 'application/vnd.ms-powerpoint' ||
    type === 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
  );
}

export function buildFaithfulCoursewareRequirement(
  sourceKind: CoursewareSourceKind,
  sourcePageCount?: number,
): string {
  const count = sourcePageCount ? `${sourcePageCount} 页` : '全部页面';
  const visualRule =
    sourceKind === 'pptx'
      ? `原 PPT 共 ${count}；以教师内容审核后保留的页面为准，最终场景数必须与审核保留页数一致，并保持这些页面的原始相对顺序、版式与视觉画布。每个保留页对应一个课堂场景，不重新绘制或改版。`
      : `固定保持原 PDF 的 ${count}、页序和内容层级，每一页对应一个课堂场景；在解析能力范围内最大程度保留原页面结构。`;

  return [
    '【转换路径：高保真还原】',
    visualRule,
    '逐页理解标题、正文、图表、公式与教师备注，讲解内容必须与当前页严格对应。',
    '为每页生成自然讲解、页面过渡、元素聚焦、高亮、激光笔和配音动作；不要只朗读标题。',
    '课堂默认自动播放，动作随讲解时间线执行，尽量不设置需要教师手动触发后才能继续的节点。',
    '不得改变原材料的事实、结论、示例含义和页面顺序。',
  ].join('\n\n');
}

/**
 * Runtime adaptation of the repository's K12 lesson-planning and lesson-
 * differentiation skills. Their Word/JSON rendering contract is deliberately
 * omitted: this prompt targets an OpenMAIC outline and narrated scene timeline.
 */
export function buildLearningSkillsEnhancementRequirement(
  teacherRequirement: string,
  sourceKind: CoursewareSourceKind,
): string {
  const teacherIntent = teacherRequirement.trim();
  return [
    '【转换路径：Learning Skills 教学增强】',
    `以教师上传的 ${sourceKind === 'pptx' ? 'PPT' : sourceKind === 'pdf' ? 'PDF' : '材料'} 为唯一内容主线，先完整理解原材料，再重构为适合课堂自动播放的 OpenMAIC 课件。允许调整页数、版式和教学顺序，但不得改变原知识范围、事实、公式、结论与案例含义。`,
    teacherIntent ? `【教师补充要求】\n${teacherIntent}` : '',
    '【先分析再设计】\n从材料中识别学科、年级段、主题、已有目标、关键概念、先备知识、词汇、常见误区和原有教学结构。信息不足时采用保守假设，并在大纲中明确标注；不得虚构课程标准代码、标准原文、来源或引用。',
    '【通用教学结构】\n形成可执行的课堂弧线：激活先备知识 → 明确目标与核心问题 → 建模/讲解 → 引导练习或探究 → 学生主动任务 → 形成性理解检测 → 总结与退出任务。时间安排要现实，不得把单页塞入过多任务。',
    '【学科路由】\n数学：采用问题驱动的 Launch–Explore–Discuss–Synthesize–Exit Ticket，覆盖基线与最易错结构案例，使用匹配概念的表格、数轴、面积模型或坐标图。\n语文/英语：保持年级适切的文本复杂度，问题必须依赖文本证据；按年级采用解码/朗读、精读、讨论、词汇、写作与退出检测。\n科学：先现象和调查、后解释；显式组织观察/数据、模型、证据推理与迁移检测，高年级加入定量推理。\n历史/社会科学：使用可争辩的核心问题，组织背景、来源分析、情境化/互证、证据论证与退出任务；没有可靠来源时不得伪造史料或链接。',
    '【分层与 UDL】\n所有学习者保持同一核心目标、情境和认知要求。默认设计 Below / At / Above 三种入口：Below 用先备知识、词汇、视觉组织器或句式支架向上衔接，支架逐步淡出且每个任务最多 1–2 个；At 完成年级目标；Above 通过分析、评价、迁移、反例或创造深化，不用“多做几题”代替挑战。分组依据形成性证据且可以调整。',
    '【必须落到课件中的教学基础设施】\n至少包含：可测学习目标；一个与学科匹配的视觉支架；具体的中途理解检测；三档判定标准（掌握/接近/需再教）；同目标的分层支持；非忙碌型提前完成任务；最后的开放反思或退出任务。',
    '【OpenMAIC 播放适配】\n把教学弧线拆成清晰场景。为每个场景生成讲解、聚焦、高亮、激光笔、必要的演示动画和 Qwen3 TTS 配音；动作按语音时间线自动执行。互动优先采用自动揭示、暂停思考、自动反馈和低操作成本形式，尽量减少教师点击。',
    '【结论动画】\n每个适合归纳的页面，把最终结论或关键启示制作成独立文本元素，不要与正文合并。该元素用于在主体内容讲解完成后通过 reveal 淡入动画自动出现，再播报结论；不得要求教师点击。',
    '【版权与真实性】\n教师上传材料只作为本次生成的来源；不逐字复制第三方专有课程文本，不伪造标准、出处、页码或已验证链接。材料未给出课程标准时，只在教师审核元数据中记录“需按本地课程标准复核”，绝对不得把来源声明、标准缺失说明、教师复核提醒或生成过程备注画进学生看到的课件页面。',
  ]
    .filter(Boolean)
    .join('\n\n');
}
