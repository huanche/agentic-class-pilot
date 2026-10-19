/** Limit the teacher's page-review tools to the page captured at send time.
 * Outlines can still describe the course, but sibling pages aren't writable. */
export function reviewSceneContext<T>(
  context: Record<string, T>,
  sceneId: string | undefined,
  currentSceneOnly: boolean,
): Record<string, T> {
  if (!currentSceneOnly) return context;
  if (!sceneId || !Object.hasOwn(context, sceneId)) return {};
  return { [sceneId]: context[sceneId] };
}
