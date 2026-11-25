/** Direct server adapters for OpenMAIC's content → actions generation path. */
import {
  applyOutlineFallbacks,
  buildCompleteScene,
  buildVisionUserContent,
  generateSceneActions,
  generateSceneContent,
  type AICallFn,
  type GeneratedSceneContent,
} from '@openmaic/generation';
import { validateScene } from '@openmaic/dsl';
import { callLLM } from '@/lib/ai/llm';
import type { BackgroundCoursewareInput } from '@/lib/generation/background-courseware';
import type { SceneOutline } from '@/lib/types/generation';
import type { Scene, SlideContent } from '@/lib/types/stage';
import { createLogger } from '@/lib/logger';
import { resolveModel } from './resolve-model';
import { llmOverrideFromConfig, type PlatformUserModelConfig } from './platform-user-model-config';
import { sortDocumentImagesForVision } from '@/lib/document/bundle';
import { resolveVocationalActive } from '@/lib/config/feature-flags';
import { generatePBLV2Project } from '@/lib/pbl/v2/agents/planner';
import { sanitizeEnhancedGeneratedContent } from '@/lib/learning-skills/enhanced-courseware-quality';
import { alignActionsToPptNarration } from '@/lib/import/ppt-narration';
import { LESSON_REQUIREMENTS, trialLearningRequirement } from '@/lib/generation/courseware-trial';
import { withSceneContentDuration } from '@/lib/generation/course-duration';
import { bindNativePptxActions, nativePptxNarrationContract } from '@/lib/onlyoffice/narration';
import {
  bindPptxAnimationsToActions,
  pptxAnimationNarrationContract,
} from '@/lib/import/pptx-animations';

export type OpenmaicContent = GeneratedSceneContent | SlideContent;
const log = createLogger('OpenMAIC courseware');

const TRIAL_SPOKEN_NARRATION = [
  '### Final spoken narration for this lesson',
  'Write each text object as the final words the teacher will say aloud, in the course language. The same words will be used for voice synthesis and captions. Keep one continuous teacher voice, with short, natural sentences and punctuation for pauses.',
  'Treat the slide, code, notes and formulas as references. Explain what they mean as you point at them. Do not read raw code, LaTeX, markup, stage directions or speaker labels. Preserve the actual facts, values, conditions and order of operations.',
  'Keep a keyword or identifier when students need it to find the matching line, then explain what it does. Read ambiguous symbols from context, abbreviations as full terms or separate letters, and numbers and units as they should be said aloud. Do not put phonetic markup or alternate readings in the speech.',
  '中文示例（只示范读法，别把例子带进不相关的课）：int a[20] → 这里声明了数组 a，里面有二十个整型元素。return a[i] → 返回数组 a 中下标为 i 的元素。x * y → x 乘以 y；*p（解引用）→ 取出指针 p 指向的值。40 B（存储大小）→ 四十个字节。',
  'Keep the required JSON action format and the timing of visual cues. If the original PPT click contract requires a bracketed step index, keep that index only as the required structural prefix.',
].join('\n');

export function createOpenmaicCoursewareSteps(
  input: BackgroundCoursewareInput,
  config: PlatformUserModelConfig | null | undefined,
  headers: Record<string, string>,
) {
  const platformOverrides = llmOverrideFromConfig(config);
  const modelFor = (stage: Parameters<typeof resolveModel>[0]['stage']) =>
    resolveModel({
      stage,
      platformOverrides,
      modelString: headers['x-model'],
      apiKey: headers['x-api-key'],
      baseUrl: headers['x-base-url'],
      providerType: headers['x-provider-type'],
    });
  const aiFor =
    (
      resolved: Awaited<ReturnType<typeof modelFor>>,
      source: string,
      signal: AbortSignal,
    ): AICallFn =>
    async (system, prompt, images) => {
      const result = await callLLM(
        {
          model: resolved.model,
          system,
          abortSignal: signal,
          maxRetries: 0,
          maxOutputTokens: resolved.modelInfo?.outputWindow,
          ...(images?.length && resolved.modelInfo?.capabilities?.vision
            ? {
                messages: [
                  { role: 'user' as const, content: buildVisionUserContent(prompt, images) },
                ],
              }
            : { prompt }),
        },
        source,
        undefined,
        resolved.thinkingConfig,
      );
      return result.text;
    };
  return {
    async content(outline: SceneOutline, signal: AbortSignal): Promise<OpenmaicContent> {
      const imported = input.importedSlides?.[outline.order - 1];
      if (
        outline.type === 'slide' &&
        input.preferImportedCanvas &&
        imported &&
        !input.formulaEnhancedOrders?.includes(outline.order)
      )
        return { type: 'slide', canvas: imported };
      const resolved = await modelFor(`scene-content:${outline.type}`);
      const vocational = resolveVocationalActive(input.requirements);
      const effective = applyOutlineFallbacks(withSceneContentDuration(outline), true, {
        allowProceduralSkill: vocational,
      });
      const ids = new Set(outline.suggestedImageIds ?? []);
      const content = await generateSceneContent(
        effective,
        aiFor(resolved, 'scene-content', signal),
        {
          assignedImages: sortDocumentImagesForVision(
            (input.pdfImages ?? []).filter((image) => ids.has(image.id)),
          ),
          imageMapping: input.imageMapping,
          visionEnabled: !!resolved.modelInfo?.capabilities?.vision,
          agents: input.agents,
          languageDirective: input.stage.languageDirective,
          userRequirements: input.requirements,
          allowProceduralSkill: vocational,
          logger: log,
          ...(effective.type === 'pbl'
            ? {
                pblLoopFallback: (plannerInput) =>
                  generatePBLV2Project(
                    plannerInput,
                    resolved.model,
                    callLLM,
                    { logger: log },
                    resolved.thinkingConfig,
                  ),
              }
            : {}),
        },
      );
      if (!content) throw new Error(`未生成页面内容：${outline.title}`);
      return sanitizeEnhancedGeneratedContent(effective, content) as GeneratedSceneContent;
    },
    async actions(
      outline: SceneOutline,
      content: OpenmaicContent,
      previous: Scene | undefined,
      signal: AbortSignal,
    ): Promise<Scene> {
      if (outline.checkpointFor) {
        const built = buildCompleteScene(
          outline,
          content as GeneratedSceneContent,
          [],
          input.stage.id,
        );
        const quiz = built?.content;
        if (
          !built ||
          quiz?.type !== 'quiz' ||
          quiz.questions.length !== 1 ||
          !quiz.questions[0].analysis?.trim() ||
          quiz.questions[0].answer?.length !== 1 ||
          !validateScene(built).valid
        ) {
          throw new Error('随堂题需要一道题、有效答案和解析');
        }
        return built as Scene;
      }
      const resolved = await modelFor('scene-actions');
      const imported =
        'type' in content && content.type === 'slide' && 'canvas' in content ? content : undefined;
      const generated = imported
        ? {
            elements: imported.canvas.elements,
            background: imported.canvas.background,
            remark: imported.canvas.script,
          }
        : (content as GeneratedSceneContent);
      // A target guides the first draft. This path never rewrites speech after TTS to fit a stopwatch.
      const seconds = outline.durationBudget?.targetSeconds;
      const nativeClicks = input.stage.nativePptx?.clicks?.[outline.id];
      let actionOutline = seconds
        ? {
            ...outline,
            description: `${outline.description}\n讲解目标约 ${seconds} 秒，可参考中文约 ${Math.round(seconds * 3.5)} 字或英文约 ${Math.round((seconds / 60) * 135)} 词。按教学内容合理组织原理、例子与步骤，不重复凑字数，不调整语速或插入等待凑时长。实际播放时长以配音为准。`,
          }
        : outline;
      actionOutline = {
        ...actionOutline,
        description:
          actionOutline.description +
          (nativeClicks
            ? nativePptxNarrationContract(nativeClicks)
            : pptxAnimationNarrationContract(imported?.canvas)),
      };
      const trial = input.stage.coursewareTrial;
      if (trial && outline.type === 'slide') {
        const level = LESSON_REQUIREMENTS[trialLearningRequirement(outline.learningRequirement)];
        const next = input.outlines
          .slice(input.outlines.indexOf(outline) + 1)
          .find((page) => !page.checkpointFor);
        actionOutline = {
          ...actionOutline,
          description: [
            actionOutline.description,
            '本节课概述：' + trial.overview,
            '本小节学习要求：' + level.label + '。' + level.instruction,
            next ? '下一小节：' + next.title + '。这里仅留自然过渡。' : '这是最后一节，简要总结。',
            '随堂题仅在答题后显示解析，课件讲稿不要念题或预告答案。',
            imported
              ? '原稿讲者备注：' + (imported.canvas.script || '无')
              : '先聚焦最终画面真实元素，再讲对应内容。',
            nativeClicks?.length
              ? '严格按点击顺序每个点击只写一段 speech，不另加开场或结尾段。等对象出现再讲该对象。退出点击执行后，讲刚刚露出的正文，禁止继续指向已消失的对象。'
              : '',
          ]
            .filter(Boolean)
            .join('\n'),
        };
      }
      const call = aiFor(resolved, 'scene-actions', signal);
      const actions = await generateSceneActions(
        actionOutline,
        generated,
        trial
          ? (system, prompt, images) =>
              call(
                [
                  system,
                  TRIAL_SPOKEN_NARRATION,
                  nativeClicks?.length
                    ? 'For this native PPTX page, the supplied click count overrides the default object count. Return exactly one text object for each click. Start its text with [1], [2], etc., in strict order. Return only text objects. Begin each segment after its click takes effect.'
                    : '',
                ]
                  .filter(Boolean)
                  .join('\n\n'),
                prompt,
                images,
              )
          : call,
        {
          ctx: {
            pageIndex: input.outlines.findIndex((page) => page.id === outline.id) + 1,
            totalPages: input.outlines.length,
            allTitles: input.outlines.map((page) => page.title),
            previousSpeeches:
              previous?.actions
                ?.filter((action) => action.type === 'speech')
                .map((action) => action.text) ?? [],
          },
          agents: input.agents,
          languageDirective: input.stage.languageDirective,
          logger: log,
          userProfile: input.requirements.userBio,
          requireModelSpeech: Boolean(trial),
        },
      );
      if (trial && nativeClicks?.length) {
        if (
          actions.length !== nativeClicks.length ||
          !actions.every(
            (action, index) =>
              action.type === 'speech' &&
              action.text.startsWith(`[${index + 1}]`) &&
              action.text.slice(String(index + 1).length + 2).trim(),
          )
        )
          throw Object.assign(new Error('讲稿与原稿动画步骤不一致，请重试本页讲稿'), {
            isRetryable: true,
          });
        for (const action of actions) {
          if (action.type === 'speech') action.text = action.text.replace(/^\[\d+\]\s*/, '');
        }
      }
      const aligned =
        outline.type === 'slide' && !trial
          ? alignActionsToPptNarration(
              actions,
              input.narrationScripts?.[outline.order - 1],
              'elements' in generated ? generated.elements : [],
              { preserveGeneratedLength: !!outline.durationBudget },
            )
          : actions;
      const built = buildCompleteScene(
        outline,
        generated,
        nativeClicks && imported
          ? bindNativePptxActions(aligned, imported.canvas, nativeClicks, Boolean(trial))
          : bindPptxAnimationsToActions(aligned, imported?.canvas),
        input.stage.id,
      );
      if (!built) throw new Error(`无法组装页面：${outline.title}`);
      const scene = { ...built, ...(imported ? { content: imported } : {}) } as Scene;
      const validation = validateScene(scene);
      if (!validation.valid)
        throw new Error(
          `页面结构无效：${validation.errors.map((issue) => `${issue.path} ${issue.message}`).join('; ')}`,
        );
      return scene;
    },
  };
}
