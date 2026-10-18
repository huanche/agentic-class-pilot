import type { Scene } from '@/lib/types/stage';
import type { SpeechAction } from '@/lib/types/action';
import type { LegacySpeechAction } from '@/lib/media/convert-legacy-asset-refs';
import { resolveActionTimeline } from '@/lib/choreography/timeline';

export function narrationKey(action: SpeechAction): string {
  return action.audioId || (action as LegacySpeechAction).audioUrl || action.id;
}

export interface PagePlaybackPosition {
  actionIndex: number;
  elapsedMs: number;
  audioDurationMs: number | null;
  speechRemainingMs: number | null;
}

/** Remaining playback, rather than lesson-plan time minus a wall clock.
 * Seeking changes the action cursor; buffering/pausing leave media time fixed.
 * Speech scales with speed; whiteboard/widget animations keep their own pace. */
export function remainingPagePlayback(
  scene: Scene,
  position: PagePlaybackPosition,
  durations: ReadonlyMap<string, number>,
  speed: number,
): { seconds: number | null; estimated: boolean } {
  if (!scene.actions?.length) return { seconds: 0, estimated: false };
  const rate = Number.isFinite(speed) && speed > 0 ? speed : 1;
  let estimated = false;
  let unresolvedVideo = false;
  const timeline = resolveActionTimeline([scene], {
    playbackSpeed: rate,
    isDiscussionSkipped: () => true,
    onUnresolvedVideoDuration: 'zero',
    getAudioDurationMs: (action) => {
      const index = scene.actions?.indexOf(action) ?? -1;
      const duration =
        index === position.actionIndex && position.audioDurationMs
          ? position.audioDurationMs
          : durations.get(narrationKey(action));
      if (index >= position.actionIndex && duration == null) estimated = true;
      return duration;
    },
  });
  let currentMs = 0;
  let futureMs = 0;
  for (const segment of timeline) {
    if (segment.actionIndex < position.actionIndex) continue;
    if (segment.action.type === 'play_video') unresolvedVideo = true;
    // Whiteboard clear duration depends on its live element count.
    if (segment.action.type === 'wb_clear') estimated = true;
    if (segment.actionIndex === position.actionIndex) currentMs += segment.advancesCursorMs;
    else futureMs += segment.advancesCursorMs;
  }
  if (unresolvedVideo) return { seconds: null, estimated: true };
  const remainingCurrent =
    position.speechRemainingMs ?? Math.max(0, currentMs - position.elapsedMs);
  return { seconds: Math.ceil((futureMs + remainingCurrent) / 1000), estimated };
}
