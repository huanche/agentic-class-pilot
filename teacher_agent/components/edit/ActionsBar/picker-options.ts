import type { Action } from '@/lib/types/action';
import type { SceneType } from '@/lib/types/stage';
import { ELEMENT_BOUND } from './cue-meta';

/** Addable cue types offered in the picker's "action" group (before discussion). */
const CUE_ORDER = ['speech', 'spotlight', 'laser'] as const;

export type PickerType = (typeof CUE_ORDER)[number];
export interface PickerOption {
  type: PickerType;
  disabled: boolean;
}

/**
 * Element-bound cues (spotlight/laser) need a slide canvas to bind to, so they
 * are only offered on slide scenes — mirrors the old header-palette filter.
 * Live discussion is no longer an addable classroom action.
 */
export function pickerOptions(sceneType: SceneType, _actions: Action[]): PickerOption[] {
  const cues = CUE_ORDER.filter((t) => sceneType === 'slide' || !ELEMENT_BOUND.has(t)).map(
    (type) => ({ type, disabled: false }),
  );
  return cues;
}
