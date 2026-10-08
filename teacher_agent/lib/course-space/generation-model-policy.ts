/** Teacher-owned course generation uses the operator's configured model/key.
 * Browser model selections belong to the standalone quick-generation flow.
 */
export function shouldUseServerGenerationModel(session: {
  courseSpaceContext?: { courseId: string };
  conversionMode?: string;
  sourceType?: string;
}): boolean {
  return (
    Boolean(session.courseSpaceContext?.courseId) ||
    Boolean(session.conversionMode) ||
    session.sourceType === 'pptx-structured-import'
  );
}
