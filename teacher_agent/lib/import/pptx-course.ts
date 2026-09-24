import type { Slide } from '@openmaic/dsl';
import type { ImportedPptSlideDraft, PptContentDraft, SceneOutline } from '@/lib/types/generation';
import { db } from '@/lib/utils/database';
import type { CourseSourceFingerprint } from '@/lib/course-governance/contracts';
import { PPT_COURSEWARE_POLICY_VERSION } from '@/lib/import/high-fidelity-courseware-policy';

export { PPT_COURSEWARE_POLICY_VERSION } from '@/lib/import/high-fidelity-courseware-policy';

const MAX_KEY_POINTS = 5;

export function cleanImportedText(value: string): string {
  if (!value.includes('<')) return value.replace(/\s+/g, ' ').trim();
  if (typeof DOMParser === 'undefined') {
    return value
      .replace(/<[^>]*>/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
  }
  const document = new DOMParser().parseFromString(value, 'text/html');
  return document.body.textContent?.replace(/\s+/g, ' ').trim() || '';
}

export function getImportedSlideText(slide: Slide): string[] {
  return slide.elements
    .filter(
      (element): element is Extract<Slide['elements'][number], { type: 'text' }> =>
        element.type === 'text',
    )
    .map((element) => cleanImportedText(element.content))
    .filter(Boolean)
    .slice(0, 30);
}

export function getImportedSlideTitle(slide: Slide, index: number): string {
  const title = getImportedSlideText(slide)[0];
  return title ? title.slice(0, 80) : `第 ${index + 1} 页`;
}

export function buildImportedPptDraft(slides: Slide[]): PptContentDraft {
  return {
    generationPolicyVersion: PPT_COURSEWARE_POLICY_VERSION,
    slides: slides.map((slide, index): ImportedPptSlideDraft => {
      const formulas = slide.elements
        .filter(
          (element): element is Extract<Slide['elements'][number], { type: 'latex' }> =>
            element.type === 'latex' && Boolean(element.latex?.trim()),
        )
        .map((element) => element.latex.trim());
      return {
        id: `pptx-slide-${index + 1}`,
        originalIndex: index,
        title: getImportedSlideTitle(slide, index),
        content: getImportedSlideText(slide).slice(1).join('\n'),
        speakerNotes: slide.script?.trim() || '',
        include: true,
        formulas,
        generationStrategy: formulas.length ? 'ai-formula-enhanced' : 'faithful',
      };
    }),
    revision: 1,
    updatedAt: Date.now(),
  };
}

/** Build a deterministic one-slide-to-one-scene outline without redrawing the PPT. */
export function buildImportedPptOutlines(slides: Slide[]): SceneOutline[] {
  return buildImportedPptOutlinesFromDraft(buildImportedPptDraft(slides));
}

export function buildImportedPptOutlinesFromDraft(draft: PptContentDraft): SceneOutline[] {
  return draft.slides
    .filter((slide) => slide.include)
    .map((slide, index) => {
      const texts = slide.content
        .split('\n')
        .map((text) => text.trim())
        .filter(Boolean);
      const notes = slide.speakerNotes.trim();
      const title = slide.title.trim() || `第 ${slide.originalIndex + 1} 页`;
      const keyPoints = texts.slice(0, MAX_KEY_POINTS);
      const formulas = slide.formulas?.filter(Boolean) ?? [];
      const formulaEnhanced =
        slide.generationStrategy === 'ai-formula-enhanced' && formulas.length > 0;

      return {
        id: slide.id,
        type: 'slide',
        title,
        description: [
          formulaEnhanced
            ? `原 PPT 第 ${slide.originalIndex + 1} 页检测到可编辑公式，本页进入 OpenMAIC 公式增强重构；保持页号、顺序、知识结论和配色风格，不沿用可能冲突的原始坐标。`
            : `严格讲解原 PPT 第 ${slide.originalIndex + 1} 页，保留该页原始视觉画布，不重新排版。`,
          texts.length ? `页面内容：${texts.join('；')}` : '本页以图形内容为主，请结合画布讲解。',
          formulas.length
            ? `必须原样使用以下 LaTeX 公式生成可编辑公式元素，不得改写变量、上下标、运算符或结论：${formulas.join('；')}`
            : '',
          notes ? `教师备注：${notes}` : '无教师备注，请根据页面可见内容补充自然讲解。',
          formulaEnhanced
            ? '重新设计公式与正文的位置，公式单独占据清晰区域，禁止与标题、正文、注释重叠；围绕公式解释变量含义、关系、直观理解和本页用途。'
            : '',
          '生成自动播放动作时，优先使用讲解、元素聚焦、高亮和激光笔，避免要求教师手动操作。',
        ]
          .filter(Boolean)
          .join('\n'),
        keyPoints: [...keyPoints, ...formulas.map((formula) => `公式：${formula}`)].slice(
          0,
          MAX_KEY_POINTS,
        ).length
          ? [...keyPoints, ...formulas.map((formula) => `公式：${formula}`)].slice(
              0,
              MAX_KEY_POINTS,
            )
          : [title],
        teachingObjective: `帮助学习者理解第 ${slide.originalIndex + 1} 页“${title}”的核心内容。`,
        estimatedDuration: 60,
        order: index + 1,
        sourceSlideOriginalIndex: slide.originalIndex,
      };
    });
}

/** Retain the reviewed PPT page identity while the outline remains editable. */
export function bindPptOutlinesToReviewedPages(
  outlines: SceneOutline[],
  draft: PptContentDraft,
): SceneOutline[] {
  const reviewed = draft.slides.filter((slide) => slide.include);
  return outlines.map((outline, index) => ({
    ...outline,
    sourceSlideOriginalIndex: outline.sourceSlideOriginalIndex ?? reviewed[index]?.originalIndex,
  }));
}

/** Resolve the final outline review to exactly the source pages it retained. */
export function resolveReviewedPptDraft(
  outlines: SceneOutline[],
  draft: PptContentDraft,
): PptContentDraft | null {
  const reviewed = draft.slides.filter((slide) => slide.include);
  if (outlines.length > reviewed.length) return null;

  const unused = new Set(reviewed.map((slide) => slide.originalIndex));
  const normalizeTitle = (value: string) => value.replace(/\s+/g, '').toLowerCase();
  const resolved = outlines.map((outline, position) => {
    let match = reviewed.find(
      (slide) =>
        slide.originalIndex === outline.sourceSlideOriginalIndex && unused.has(slide.originalIndex),
    );
    match ??= reviewed.find((slide) => slide.id === outline.id && unused.has(slide.originalIndex));
    match ??= reviewed.find(
      (slide) =>
        normalizeTitle(slide.title) === normalizeTitle(outline.title) &&
        unused.has(slide.originalIndex),
    );
    match ??= reviewed.find((slide, index) => index >= position && unused.has(slide.originalIndex));
    match ??= reviewed.find((slide) => unused.has(slide.originalIndex));
    if (match) unused.delete(match.originalIndex);
    return match;
  });

  if (resolved.some((slide) => !slide)) return null;
  return {
    ...draft,
    slides: resolved.filter((slide): slide is ImportedPptSlideDraft => Boolean(slide)),
    revision: draft.revision + 1,
    updatedAt: Date.now(),
  };
}

export function buildImportedPptContextFromDraft(draft: PptContentDraft): string {
  return draft.slides
    .filter((slide) => slide.include)
    .map(
      (slide) =>
        `【第 ${slide.originalIndex + 1} 页】\n页面标题：${slide.title || '未命名'}\n页面文字：${slide.content || '无可提取文字，需结合页面图形理解。'}\n教师备注：${slide.speakerNotes || '无教师备注，请根据页面内容补充讲解。'}${slide.teacherComment ? `\n教师修订意见：${slide.teacherComment}` : ''}`,
    )
    .join('\n\n');
}

export function buildImportedPptContext(slides: Slide[]): string {
  return slides
    .map((slide, index) => {
      const text = getImportedSlideText(slide).join('\n');
      const notes = slide.script?.trim() || '无教师备注，请根据页面内容补充讲解。';
      return `【第 ${index + 1} 页】\n页面文字：${text || '无可提取文字，需结合页面图形理解。'}\n教师备注：${notes}`;
    })
    .join('\n\n');
}

export async function storeImportedPptSlides(
  id: string,
  slides: Slide[],
  source?: CourseSourceFingerprint,
): Promise<void> {
  await db.pptxImports.put({ id, slides, source, createdAt: Date.now() });
}

export async function loadImportedPptSlides(id?: string): Promise<Slide[] | null> {
  if (!id) return null;
  return (await db.pptxImports.get(id))?.slides ?? null;
}

export async function removeImportedPptSlides(id?: string): Promise<void> {
  if (id) await db.pptxImports.delete(id);
}
