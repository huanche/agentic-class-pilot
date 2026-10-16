import { teacherReturnUrl } from './navigation';

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

/** A lost tab session must not switch a course to a stale browser model. */
export function resolveClassroomGenerationModelPolicy(input: {
  persistedPolicy?: 'server' | 'browser';
  sessionPreference?: unknown;
  embeddedCourseWorkspace?: boolean;
  returnTo?: string | null;
}): 'server' | 'browser' {
  if (input.persistedPolicy) return input.persistedPolicy;
  if (typeof input.sessionPreference === 'boolean')
    return input.sessionPreference ? 'server' : 'browser';
  const parent = teacherReturnUrl(input.returnTo, '');
  return input.embeddedCourseWorkspace ||
    /^\/(course-space|teacher-workspace)([/?#]|$)/.test(parent)
    ? 'server'
    : 'browser';
}
