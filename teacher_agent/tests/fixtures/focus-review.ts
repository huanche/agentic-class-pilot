/** A deterministic reviewer for tests of routing/transport rather than semantics. */
export function approveFocusReview(user: string): string {
  const data = JSON.parse(user) as { segments: Array<{ speechId: string; targetIds: string[] }> };
  return JSON.stringify({
    segments: data.segments.map((segment) => ({
      speechId: segment.speechId,
      targetIds: segment.targetIds,
      matches: true,
      singleTopic: true,
      reason: '',
    })),
  });
}

/** A minimal plan for transport tests; semantic behavior is tested separately. */
export function fixtureTeachingPlan(targetId: string | null = null, speech = '本页概览。'): string {
  return JSON.stringify({
    segments: [
      { kind: 'narration', purpose: targetId ? 'explanation' : 'overview', targetId, speech },
    ],
  });
}
