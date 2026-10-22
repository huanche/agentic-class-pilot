import type { Action } from '@openmaic/dsl';
import { measureScenePlaybackSeconds } from './course-duration';
import type { Scene } from '@/lib/types/stage';

/** A planning estimate, never an audio measurement or a reason to change playback speed. */
export interface NarrationPace {
  unitsPerSecond: number;
  samples: number;
}

export interface NarrationRevision {
  actions: Action[];
  audioSeconds?: Record<string, number>;
}

/** Spoken-length proxy: avoid treating Latin code characters as Chinese syllables. */
export function narrationUnits(text: string): number {
  let units = 0;
  for (const character of text.normalize('NFKC')) {
    if (/\p{Script=Han}/u.test(character)) units += 1;
    else if (/[A-Za-z]/u.test(character)) units += 1 / 3;
    else if (/\p{N}/u.test(character)) units += 1;
    else if (/[。！？.!?；;，,：:]/u.test(character)) units += 0.3;
    else if (/\p{L}/u.test(character)) units += 1;
    else if (!/\s/u.test(character)) units += 0.15;
  }
  return units;
}

export function validNarrationPace(pace?: NarrationPace): pace is NarrationPace {
  return Boolean(
    pace &&
    Number.isFinite(pace.unitsPerSecond) &&
    pace.unitsPerSecond >= 0.3 &&
    pace.unitsPerSecond <= 30 &&
    Number.isSafeInteger(pace.samples) &&
    pace.samples > 0,
  );
}

/** Per-run observations are isolated by exact voice/config identity, including credentials. */
export function createNarrationPace() {
  let identity: string | undefined;
  const samples = new Map<string, { units: number; seconds: number }>();
  return {
    observe(sample: { identity: string; text: string; seconds: number; speed?: number }) {
      if (
        !Number.isFinite(sample.seconds) ||
        sample.seconds < 1 ||
        !Number.isFinite(sample.speed ?? 1) ||
        (sample.speed ?? 1) !== 1
      )
        return;
      const units = narrationUnits(sample.text);
      if (units < 10 || units / sample.seconds < 0.3 || units / sample.seconds > 30) return;
      if (identity !== sample.identity) {
        identity = sample.identity;
        samples.clear();
      }
      samples.set(sample.text, { units, seconds: sample.seconds });
      // Bound memory while keeping the latest observations of this voice.
      if (samples.size > 128) samples.delete(samples.keys().next().value!);
    },
    estimate(): NarrationPace | undefined {
      if (!samples.size) return undefined;
      const values = [...samples.values()];
      return {
        unitsPerSecond:
          values.reduce((s, v) => s + v.units, 0) / values.reduce((s, v) => s + v.seconds, 0),
        samples: values.length,
      };
    },
    durations(actions: Action[]): Record<string, number> {
      return Object.fromEntries(
        actions.flatMap((action) => {
          const measured =
            action.type === 'speech' && (action.speed ?? 1) === 1
              ? samples.get(action.text)?.seconds
              : undefined;
          return measured ? [[action.id, measured]] : [];
        }),
      );
    },
  };
}

export function estimateNarrationSeconds(
  actions: Action[],
  pace: NarrationPace,
  measured: Record<string, number> = {},
): number | undefined {
  if (!validNarrationPace(pace)) return undefined;
  const durations = Object.fromEntries(
    actions.flatMap((a) =>
      a.type === 'speech'
        ? [
            [
              a.id,
              Number.isFinite(measured[a.id]) && measured[a.id] > 0
                ? measured[a.id]
                : narrationUnits(a.text) / pace.unitsPerSecond / (a.speed ?? 1),
            ],
          ]
        : [],
    ),
  );
  return measureScenePlaybackSeconds({ actions } as Scene, durations);
}

/** Preserve every non-speech action and every untargeted paragraph byte for byte. */
export function applyNarrationRevisions(
  actions: Action[],
  response: string,
  editableIds: string[],
): Action[] {
  const parsed: unknown = JSON.parse(
    response
      .trim()
      .replace(/^```(?:json)?\s*/i, '')
      .replace(/\s*```$/, ''),
  );
  if (
    !parsed ||
    typeof parsed !== 'object' ||
    !('revisions' in parsed) ||
    !Array.isArray(parsed.revisions) ||
    !parsed.revisions.length ||
    Object.keys(parsed).some((key) => key !== 'revisions')
  )
    throw new Error('Expected narration revisions');
  const replacements = new Map<string, string>();
  for (const change of parsed.revisions) {
    if (
      !change ||
      typeof change !== 'object' ||
      Object.keys(change).some((key) => key !== 'speechId' && key !== 'text') ||
      typeof change.speechId !== 'string' ||
      !editableIds.includes(change.speechId) ||
      replacements.has(change.speechId) ||
      typeof change.text !== 'string' ||
      !change.text.trim() ||
      change.text.length > 10000 ||
      !actions.some((a) => a.type === 'speech' && a.id === change.speechId)
    )
      throw new Error('Revision changed an unapproved speech or supplied invalid text');
    replacements.set(change.speechId, change.text);
  }
  const allocated = new Set(actions.map((action) => action.id));
  return actions.map((action) => {
    if (action.type !== 'speech') return { ...action };
    const {
      audioId: _audioId,
      audioUrl: _audioUrl,
      audioRef: _audioRef,
      ...speech
    } = action as typeof action & { audioUrl?: string; audioRef?: string };
    const replacement = replacements.get(action.id);
    // New candidate identities isolate ALL stable files from a saved predecessor.
    // Unchanged text still reuses its exact cached bytes; rollback cannot delete
    // predecessor audio after a partially finalized or rejected checkpoint.
    let id = `${action.id}_revision`;
    let sequence = 1;
    while (allocated.has(id)) id = `${action.id}_revision_${sequence++}`;
    allocated.add(id);
    return { ...speech, id, text: replacement ?? action.text, audioInvalidated: true };
  });
}
