/**
 * Scene Actions Generation API
 *
 * Generates actions for a scene given its outline and content,
 * then assembles the complete Scene object.
 * This is the second half of the two-step scene generation pipeline.
 */

import { NextRequest } from 'next/server';
import { callLLM } from '@/lib/ai/llm';
import {
  generateSceneActions,
  buildCompleteScene,
  buildVisionUserContent,
  type SceneGenerationContext,
  type AgentInfo,
} from '@openmaic/generation';
import { FORMULA_NARRATION_MARKER } from '@/lib/import/ppt-narration';
import type { SceneOutline } from '@/lib/types/generation';
import type {
  GeneratedSlideContent,
  GeneratedQuizContent,
  GeneratedInteractiveContent,
  GeneratedPBLContent,
} from '@/lib/types/generation';
import type { SpeechAction } from '@/lib/types/action';
import type { PBLContent, SlideContent } from '@/lib/types/stage';
import { createLogger } from '@/lib/logger';
import { normalizeLegacyPBLContent } from '@/lib/pbl/legacy/read';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import { llmApiError } from '@/lib/server/llm-error-response';
import { resolveModelFromRequest } from '@/lib/server/resolve-model';
import { alignActionsToPptNarration } from '@/lib/import/ppt-narration';
import { withEnhancedChoreographyContract } from '@/lib/learning-skills/enhanced-courseware-quality';

const log = createLogger('Scene Actions API');

export const maxDuration = 60;

export async function POST(req: NextRequest) {
  let outlineTitle: string | undefined;
  let resolvedModelString: string | undefined;
  try {
    const body = await req.json();
    const {
      outline,
      allOutlines,
      content,
      stageId,
      agents,
      previousSpeeches: incomingPreviousSpeeches,
      userProfile,
      languageDirective,
      narrationScript,
    } = body as {
      outline: SceneOutline;
      allOutlines: SceneOutline[];
      content:
        | GeneratedSlideContent
        | GeneratedQuizContent
        | GeneratedInteractiveContent
        | GeneratedPBLContent
        | PBLContent
        | SlideContent;
      stageId: string;
      agents?: AgentInfo[];
      previousSpeeches?: string[];
      userProfile?: string;
      languageDirective?: string;
      narrationScript?: string;
    };

    // Validate required fields
    if (!outline) {
      return apiError('MISSING_REQUIRED_FIELD', 400, 'outline is required');
    }
    if (!allOutlines || allOutlines.length === 0) {
      return apiError(
        'MISSING_REQUIRED_FIELD',
        400,
        'allOutlines is required and must not be empty',
      );
    }
    if (!content) {
      return apiError('MISSING_REQUIRED_FIELD', 400, 'content is required');
    }
    if (!stageId) {
      return apiError('MISSING_REQUIRED_FIELD', 400, 'stageId is required');
    }

    // ── Model resolution from request headers/body ──
    const {
      model: languageModel,
      modelInfo,
      modelString,
      thinkingConfig,
    } = await resolveModelFromRequest(req, body, 'scene-actions');
    outlineTitle = outline?.title;
    resolvedModelString = modelString;

    // Detect vision capability
    const hasVision = !!modelInfo?.capabilities?.vision;

    // AI call function (actions typically don't use vision, but kept for consistency)
    const aiCall = async (
      systemPrompt: string,
      userPrompt: string,
      images?: Array<{ id: string; src: string }>,
    ): Promise<string> => {
      if (images?.length && hasVision) {
        const result = await callLLM(
          {
            model: languageModel,
            system: systemPrompt,
            messages: [
              {
                role: 'user' as const,
                content: buildVisionUserContent(userPrompt, images),
              },
            ],
            maxOutputTokens: modelInfo?.outputWindow,
            maxRetries: 0,
          },
          'scene-actions',
          undefined,
          thinkingConfig,
        );
        return result.text;
      }
      const result = await callLLM(
        {
          model: languageModel,
          system: systemPrompt,
          prompt: userPrompt,
          maxOutputTokens: modelInfo?.outputWindow,
          maxRetries: 0,
        },
        'scene-actions',
        undefined,
        thinkingConfig,
      );
      return result.text;
    };

    // ── Build cross-scene context ──
    const allTitles = allOutlines.map((o) => o.title);
    const pageIndex = allOutlines.findIndex((o) => o.id === outline.id);
    const ctx: SceneGenerationContext = {
      pageIndex: (pageIndex >= 0 ? pageIndex : 0) + 1,
      totalPages: allOutlines.length,
      allTitles,
      previousSpeeches: incomingPreviousSpeeches ?? [],
    };

    // ── Generate actions ──
    log.info(`Generating actions: "${outline.title}" (${outline.type}) [model=${modelString}]`);

    const importedSlideContent =
      'type' in content && content.type === 'slide' && 'canvas' in content ? content : undefined;
    // Action generation needs the compact generated-content shape, while the
    // persisted scene must retain the importer's complete Slide canvas (theme,
    // viewport, animations, notes and every original element).
    const generationContent = (
      importedSlideContent
        ? {
            elements: importedSlideContent.canvas.elements,
            background: importedSlideContent.canvas.background,
            remark: importedSlideContent.canvas.script,
          }
        : 'type' in content && content.type === 'pbl'
          ? normalizeLegacyPBLContent(content)
          : content
    ) as
      | GeneratedSlideContent
      | GeneratedQuizContent
      | GeneratedInteractiveContent
      | GeneratedPBLContent;

    const isFormulaEnhancedPage = narrationScript?.includes(FORMULA_NARRATION_MARKER) === true;
    const narrationContract = isFormulaEnhancedPage
      ? `【公式增强页讲稿合同】
1. 中文讲稿控制在 260–420 字；公式较多或页面知识点较多时可到 500 字，不得因追求简短而漏掉页面主要结论。
2. 讲解顺序必须是：承接上一页 → 本页问题/结论 → 公式整体用途 → 关键项的物理意义 → 各项关系与直观理解 → 本页总结或下一页过渡。
3. 必须覆盖“本页公式（LaTeX）”列出的每一个公式。短公式可用自然语言读出关系；长公式禁止逐字符、逐运算符或朗读 LaTeX，只介绍每一项、上下标、系数、积分/求和区间的物理意义。
4. 公式中的符号要按学科语义播报，例如 P 表示功率、G 表示增益、下标 TX/RX 表示发射端/接收端；仅在页面材料能够支持时解释，不能猜测。
5. 至少安排一次公式元素聚焦或激光笔动作，并让该动作与对应解释相邻。讲稿必须是可直接交给 TTS 的自然口语，不得包含 LaTeX 源码。`
      : '中文总讲稿控制在 140–200 字，只讲一个核心逻辑，避免重复标题和罗列全部文字。';
    const narrationAwareOutline = narrationScript
      ? {
          ...outline,
          description: `${outline.description}\n\n【高保真 PPT 讲解约束】\n${narrationScript}\n请参考 OpenMAIC 的逐页讲解方式：先理解本页视觉内容，再用自然口语解释“为什么、如何理解或如何应用”，不要逐字朗读页面。选择一个最有帮助的例子、类比或观察提示，并用一句短过渡承接上一页或引出下一页。所有内容必须以本页材料为依据，不得混入其他页面。\n${narrationContract}`,
        }
      : outline;
    const actionOutline = withEnhancedChoreographyContract(narrationAwareOutline);
    const generatedActions = await generateSceneActions(
      actionOutline,
      generationContent,
      aiCall,
      {
        ctx,
        agents,
        userProfile,
        languageDirective,
      },
    );
    const actions = alignActionsToPptNarration(
      generatedActions,
      narrationScript,
      'elements' in generationContent ? generationContent.elements : [],
    );

    log.info(`Generated ${actions.length} actions for: "${outline.title}"`);

    // ── Build complete scene ──
    const builtScene = buildCompleteScene(outline, generationContent, actions, stageId);
    const scene =
      builtScene?.type === 'slide' && importedSlideContent
        ? {
            ...builtScene,
            content: { type: 'slide' as const, canvas: importedSlideContent.canvas },
          }
        : builtScene;

    if (!scene) {
      log.error(`Failed to build scene: "${outline.title}"`);

      return apiError('GENERATION_FAILED', 500, `Failed to build scene: ${outline.title}`);
    }

    // ── Extract speeches for cross-scene coherence ──
    const outputPreviousSpeeches = (scene.actions || [])
      .filter((a): a is SpeechAction => a.type === 'speech')
      .map((a) => a.text);

    log.info(
      `Scene assembled successfully: "${outline.title}" — ${scene.actions?.length ?? 0} actions`,
    );

    return apiSuccess({ scene, previousSpeeches: outputPreviousSpeeches });
  } catch (error) {
    log.error(
      `Scene actions generation failed [scene="${outlineTitle ?? 'unknown'}", model=${resolvedModelString ?? 'unknown'}]:`,
      error,
    );
    return llmApiError(error);
  }
}
