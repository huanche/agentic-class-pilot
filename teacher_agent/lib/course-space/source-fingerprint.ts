import type { GenerationSessionState } from '@/app/generation-preview/types';
import { fingerprintCoursewareFile } from '@/lib/course-governance/fingerprint';

/**
 * Enhanced document bundles use an immutable snapshot of the exact extracted
 * input, not a fabricated hash of an original PDF/PPT. PPTX canvas imports and
 * faithful conversion retain their original-file fingerprint requirement.
 * Also repairs previously saved workspace sessions without repeating extraction.
 */
export async function ensureCoursewareSourceFingerprint(
  session: GenerationSessionState,
): Promise<GenerationSessionState> {
  const context = session.courseSpaceContext;
  const materialIds = context?.materialIds?.length
    ? context.materialIds
    : context?.materialId
      ? [context.materialId]
      : [];
  if (
    session.sourceFingerprint ||
    session.conversionMode !== 'learning-skills-enhanced' ||
    !context?.courseId ||
    !materialIds.length ||
    !session.pdfText.trim() ||
    session.pptxImportStorageKey ||
    session.pptContentDraft
  ) {
    return session;
  }
  const snapshot = JSON.stringify({
    version: 1,
    kind: 'course-material-extraction',
    courseId: context.courseId,
    materialIds,
    text: session.pdfText,
  });
  const file = new File([snapshot], '课程资料解析内容.json', {
    type: 'application/json',
    lastModified: 0,
  });
  return { ...session, sourceFingerprint: await fingerprintCoursewareFile(file, 0) };
}
