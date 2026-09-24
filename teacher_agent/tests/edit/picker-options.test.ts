import { describe, expect, test } from 'vitest';
import { pickerOptions } from '@/components/edit/ActionsBar/picker-options';
import type { Action } from '@/lib/types/action';

const A = (id: string, type = 'speech'): Action => ({ id, type }) as unknown as Action;

describe('pickerOptions', () => {
  test('slide scene offers narration and visual cues, but no discussion', () => {
    expect(pickerOptions('slide', []).map((o) => o.type)).toEqual(['speech', 'spotlight', 'laser']);
  });
  test('non-slide scenes drop element-bound cues', () => {
    expect(pickerOptions('interactive', []).map((o) => o.type)).toEqual(['speech']);
    expect(pickerOptions('pbl', []).map((o) => o.type)).toEqual(['speech']);
    expect(pickerOptions('quiz', []).map((o) => o.type)).toEqual(['speech']);
  });
  test('old discussion actions do not restore the removed picker entry', () => {
    const opts = pickerOptions('slide', [A('d', 'discussion')]);
    expect(opts.map((o) => o.type)).toEqual(['speech', 'spotlight', 'laser']);
    expect(opts.find((o) => o.type === 'speech')?.disabled).toBe(false);
  });
});
