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
