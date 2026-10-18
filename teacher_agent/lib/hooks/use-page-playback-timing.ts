'use client';

import { useEffect, useState, type RefObject } from 'react';
import type { Scene } from '@/lib/types/stage';
import type { PlaybackEngine } from '@/lib/playback/engine';
import { measureAudioDuration } from '@/lib/audio/audio-duration';
import { resolveAudioBlob } from '@/lib/media/resolve-audio-bytes';
import { isConcreteMediaAddress } from '@/lib/media/resolve-media-ref';
import { narrationKey, remainingPagePlayback } from '@/lib/playback/page-timing';

export function usePagePlaybackTiming(
  scene: Scene | null | undefined,
  engineRef: RefObject<PlaybackEngine | null>,
) {
  const [timing, setTiming] = useState<{
    sceneId: string;
    seconds: number | null;
    estimated: boolean;
  }>();

  useEffect(() => {
    if (!scene || !['slide', 'interactive'].includes(scene.type)) return;
    const controller = new AbortController();
    const durations = new Map<string, number>();
    const update = () => {
      const engine = engineRef.current;
      const position =
        engine?.getCurrentSceneId() === scene.id ? engine.getPlaybackPosition() : null;
      const action = position && scene.actions?.[position.actionIndex];
      if (action?.type === 'speech' && position?.audioDurationMs) {
        durations.set(narrationKey(action), position.audioDurationMs);
      }
      const next = remainingPagePlayback(
        scene,
        position ?? {
          actionIndex: 0,
          elapsedMs: 0,
          audioDurationMs: null,
          speechRemainingMs: null,
        },
        durations,
      );
      setTiming((previous) =>
        previous?.sceneId === scene.id &&
        previous.seconds === next.seconds &&
        previous.estimated === next.estimated
          ? previous
          : { sceneId: scene.id, ...next },
      );
    };
    update();
    const timer = window.setInterval(update, 200);
    // Read current media bytes, not a potentially stale mirrored duration.
    // Two workers bound memory and network pressure for long narrated pages.
    const keys = [
      ...new Set(
        (scene.actions ?? []).filter((action) => action.type === 'speech').map(narrationKey),
      ),
    ];
    const worker = async () => {
      while (keys.length && !controller.signal.aborted) {
        const key = keys.shift()!;
        try {
          const blob = isConcreteMediaAddress(key)
            ? await fetch(key, { signal: controller.signal }).then((response) =>
                response.ok ? response.blob() : null,
              )
            : await resolveAudioBlob(key);
          if (!blob || controller.signal.aborted) continue;
          const duration = measureAudioDuration(
            await blob.arrayBuffer(),
            blob.type.replace('audio/', ''),
          );
          if (
            duration != null &&
            Number.isFinite(duration) &&
            duration > 0 &&
            !controller.signal.aborted
          ) {
            // The playing media element is authoritative if it resolved first.
            if (!durations.has(key)) durations.set(key, duration * 1000);
            update();
          }
        } catch {
          /* Unknown/missing audio keeps an explicitly estimated clock. */
        }
      }
    };
    void worker();
    void worker();
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [scene, engineRef]);

  return timing?.sceneId === scene?.id ? timing : undefined;
}
