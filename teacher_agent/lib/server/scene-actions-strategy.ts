import { generateSceneActions, type SceneActionsOptions } from '@openmaic/generation';
import type { Action } from '@/lib/types/action';
import { generateAlignedSceneActions } from './aligned-scene-actions';

/** Whole-course and teacher-requested page regeneration use the same action strategy. */
export async function generateCoursewareSceneActions(
  outline: Parameters<typeof generateSceneActions>[0],
  content: Parameters<typeof generateSceneActions>[1],
  aiCall: Parameters<typeof generateSceneActions>[2],
  options: SceneActionsOptions & { transformActions?: (actions: Action[]) => Action[] } = {},
): Promise<Action[]> {
  if (process.env.COURSEWARE_GENERATION_ENGINE !== 'openmaic')
    return generateAlignedSceneActions(outline, content, aiCall, options);
  const { transformActions, ...generationOptions } = options;
  const actions = await generateSceneActions(outline, content, aiCall, generationOptions);
  return transformActions ? transformActions(actions) : actions;
}
