import type { SceneOutline } from '@/lib/types/generation';
import type { GenerationSessionState } from '@/app/generation-preview/types';

/** Summarize the actual outline without another model call. */
export function lessonOverviewFromOutlines(outlines: SceneOutline[]): string {
  const pages = outlines.filter((page) => page.title.trim());
  if (!pages.length) return '';
  const topics = pages.map((page) => page.title.trim()).join('；');
  const points = [
    ...new Set(
      pages.flatMap((page) =>
        (page.keyPoints ?? [])
          .filter(
            (point) =>
              !/^(聚焦|高亮|框选|重点框选|激光|用激光|页面过渡|放大|拆解)/.test(point.trim()),
          )
          .slice(0, 1),
      ),
    ),
  ].slice(0, 6);
  return [
    `本节课依次围绕以下内容展开：${topics}。`,
    points.length ? `学习重点：${points.join('；')}。` : '',
  ]
    .filter(Boolean)
    .join('\n\n')
    .slice(0, 4000);
}

export function sessionWithLessonOverview(session: GenerationSessionState, overview: string) {
  const trimmed = overview.trim();
  if (!trimmed || trimmed.length > 4000) throw new Error('请填写本节课概述，最多 4000 字。');
  const base = session.outlineBaseRequirement ?? session.requirements.requirement;
  return {
    ...session,
    lessonOverview: trimmed,
    outlineBaseRequirement: base,
    requirements: {
      ...session.requirements,
      requirement: `${base}\n\n【教师修订的本节课概述】\n${trimmed}\n\n请据此重新生成本节课大纲，以修订后的概述确定重点和教学顺序；仍以原资料为依据，遵守已选转换模式、课时范围和时长。${session.conversionMode === 'faithful' ? '高保真模式仍保持教师保留页面的原始页序、页数和画布，只调整各页讲解重点，不重新绘制页面。' : ''}`,
    },
  };
}
