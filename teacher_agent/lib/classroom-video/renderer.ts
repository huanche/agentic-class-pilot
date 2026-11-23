import type { Stage } from '@/lib/types/stage';

/** Keep the native PPTX and regular courseware paths on the established recorder. */
export function usesTimelineVideo(stage: Stage): boolean {
  return stage.coursewareTrial?.mode === 'learning-skills-enhanced' && !stage.nativePptx;
}

export const TIMELINE_VIDEO_RENDERER = 'openmaic-timeline-v1' as const;
