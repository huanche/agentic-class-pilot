import type { PPTElement } from '@openmaic/dsl';
import type { GeneratedSlideContent, SceneOutline } from '@/lib/types/generation';
import type { Scene } from '@/lib/types/stage';

export const LEARNING_SKILLS_ENHANCED_MARKER = '【转换路径：Learning Skills 教学增强】';

const TEACHER_ONLY_NOTICE_PATTERNS = [
  /本课内容重建自教师上传/u,
  /未添加外部课程标准/u,
  /建议教师.{0,12}课程标准.{0,12}复核/u,
  /仅供教师审核/u,
  /教师审核后/u,
];

const INCOMPLETE_SLIDE_PATTERNS = [
  /利用独立文本元素/u,
  /reveal 动画/u,
  /退出任务收集/u,
  /Below\s*\/\s*At\s*\/\s*Above/iu,
  /非忙碌型提前完成任务/u,
  /形成性证据/u,
];

function plainText(value: string): string {
  return value.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
}

export function isLearningSkillsEnhancedOutline(outline: Pick<SceneOutline, 'description'>): boolean {
  return outline.description.includes(LEARNING_SKILLS_ENHANCED_MARKER);
}

export function isTeacherOnlyGeneratedNotice(value: string): boolean {
  const text = plainText(value);
  return TEACHER_ONLY_NOTICE_PATTERNS.some((pattern) => pattern.test(text));
}

/** Detect AI-enhanced scenes that contain generation plans instead of lessons. */
export function isIncompleteEnhancedScene(outline: SceneOutline, scene: Scene): boolean {
  if (scene.type !== 'slide') return false;
  const canvas = scene.content.type === 'slide' ? scene.content.canvas : undefined;
  if (!canvas) return false;
  const text = canvas.elements
    .filter((element) => element.type === 'text')
    .map((element) => plainText(element.content))
    .join(' ');
  if (INCOMPLETE_SLIDE_PATTERNS.some((pattern) => pattern.test(text))) return true;
  const teachingElements = canvas.elements.filter(
    (element) => element.type !== 'text' || plainText(element.content) !== scene.title,
  );
  return (
    teachingElements.length <= 1 &&
    !(scene.actions ?? []).some((action) => action.type === 'speech')
  );
}

/** Keep governance/review notices out of the student-facing generated canvas. */
export function removeTeacherOnlyNotices(content: GeneratedSlideContent): GeneratedSlideContent {
  const elements = content.elements.filter((element) => {
    if (element.type !== 'text') return true;
    return !isTeacherOnlyGeneratedNotice(element.content);
  });
  return elements.length === content.elements.length ? content : { ...content, elements };
}

export function withEnhancedChoreographyContract(outline: SceneOutline): SceneOutline {
  if (!isLearningSkillsEnhancedOutline(outline)) return outline;
  return {
    ...outline,
    description: `${outline.description}

【AI 增强课件播放动作强约束】
1. 学生课件画布只呈现教学内容。不得把来源声明、课程标准缺失、教师复核提醒、生成说明或其它后台治理备注画到页面中。
2. 将讲解拆成若干知识点，每个视觉动作必须与紧随其后的 speech 成对：先 spotlight 或 laser 指向当前正在解释的元素，再立即播报该元素对应的概念、图表、步骤或公式。
3. speech 必须明确说出或自然转述目标元素的可见内容；禁止讲解 A 时高亮 B，也禁止先播报后才高亮。
4. 只选择当前页真实存在、与知识点直接相关的元素 ID。不要高亮背景、装饰线、页码、来源说明或整页无关容器。
5. 一个 speech 同时讲多个知识点时应拆分，并分别绑定对应元素；没有可靠目标时只讲解，不生成错误的视觉动作。
6. 若页面有独立的“结论、总结、关键启示”元素，在主体知识点全部讲完后生成 reveal 动作，使该元素自动淡入，再紧接 speech 解释结论。不得提前显示或依赖教师点击。`,
  };
}

export function sanitizeEnhancedGeneratedContent(
  outline: SceneOutline,
  content:
    | GeneratedSlideContent
    | { questions: unknown[] }
    | { html: string }
    | { projectV2: unknown },
): typeof content {
  if (!isLearningSkillsEnhancedOutline(outline) || !('elements' in content)) return content;
  return removeTeacherOnlyNotices(content as GeneratedSlideContent) as typeof content;
}
