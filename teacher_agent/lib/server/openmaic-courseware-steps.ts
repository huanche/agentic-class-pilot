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
import { withSceneContentDuration } from '@/lib/generation/course-duration';
import {
  bindPptxAnimationsToActions,
  pptxAnimationNarrationContract,
} from '@/lib/import/pptx-animations';

export type OpenmaicContent = GeneratedSceneContent | SlideContent;
const log = createLogger('OpenMAIC courseware');

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
      let actionOutline = seconds
        ? {
            ...outline,
            description: `${outline.description}\n讲解目标约 ${seconds} 秒，可参考中文约 ${Math.round(seconds * 3.5)} 字或英文约 ${Math.round((seconds / 60) * 135)} 词。按教学内容合理组织原理、例子与步骤，不重复凑字数，不调整语速或插入等待凑时长。实际播放时长以配音为准。`,
          }
        : outline;
      actionOutline = {
        ...actionOutline,
        description: actionOutline.description + pptxAnimationNarrationContract(imported?.canvas),
      };
      const actions = await generateSceneActions(
        actionOutline,
        generated,
        aiFor(resolved, 'scene-actions', signal),
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
        },
      );
      const aligned = alignActionsToPptNarration(
        actions,
        input.narrationScripts?.[outline.order - 1],
        'elements' in generated ? generated.elements : [],
        { preserveGeneratedLength: !!outline.durationBudget },
      );
      const built = buildCompleteScene(
        outline,
        generated,
        bindPptxAnimationsToActions(aligned, imported?.canvas),
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
