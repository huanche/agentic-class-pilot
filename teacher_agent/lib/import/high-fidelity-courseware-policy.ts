/**
 * Stable generation contract for teacher-owned PPTX courseware.
 *
 * Bump the version whenever a change can alter page routing, narration limits,
 * source-canvas geometry or the final scene ordering. Persisting the version in
 * the reviewed draft makes generated courses reproducible and auditable.
 */
export const HIGH_FIDELITY_COURSEWARE_POLICY = Object.freeze({
  version: 'ppt-high-fidelity-v2',
  narration: Object.freeze({
    regularMaxChars: 220,
    formulaMaxChars: 520,
  }),
  viewport: Object.freeze({
    bottomPadding: 12,
    overflowTolerance: 4,
    maxReasonableBottomFactor: 1.5,
  }),
});

export const PPT_COURSEWARE_POLICY_VERSION = HIGH_FIDELITY_COURSEWARE_POLICY.version;
