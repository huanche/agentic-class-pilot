import { describe, expect, it } from 'vitest';
import {
  resolveCourseMinutes,
  planCourseDuration,
  withCourseDurationRequirement,
  withNarrationDuration,
  withSceneContentDuration,
  assessCourseDuration,
  calibrateNarrationDuration,
  durationMeasurementKey,
  measureScenePlaybackSeconds,
} from '@/lib/generation/course-duration';
import type { SceneOutline } from '@/lib/types/generation';
import type { Scene } from '@/lib/types/stage';

const page = (id: string, seconds = 60): SceneOutline => ({
  id,
  type: 'slide',
  title: id,
  description: '原始知识点',
  keyPoints: [],
  order: Number(id),
  estimatedDuration: seconds,
});
const scene = (seconds?: number): Scene =>
  ({
    id: 'scene',
    stageId: 'stage',
    type: 'slide',
    title: 'Page',
    order: 1,
    content: { type: 'slide', canvas: { elements: [] } },
    actions: [],
    timing: { plannedDurationSec: 120, measuredDurationSec: seconds },
  }) as unknown as Scene;

describe('course duration contract', () => {
  it('defaults an omitted input to 28 minutes, and validates explicit input', () => {
    for (const value of [undefined, null, '', '  ']) expect(resolveCourseMinutes(value)).toBe(28);
    expect(resolveCourseMinutes('20')).toBe(20);
    for (const value of [0, -2, 1.5, 'abc', Infinity]) {
      expect(() => resolveCourseMinutes(value)).toThrow();
    }
  });

  it('replaces model estimates with budgets adding up to the teacher target', () => {
    const original = Array.from({ length: 10 }, (_, i) => page(String(i + 1)));
    const planned = planCourseDuration(original, 20);
    expect(planned.reduce((sum, outline) => sum + outline.estimatedDuration!, 0)).toBe(1200);
    expect(original[0].estimatedDuration).toBe(60);
    expect(planned.every((outline) => outline.durationBudget?.targetSeconds === 120)).toBe(true);
  });

  it('preserves relative difficulty and does not count learner-controlled activities', () => {
    const planned = planCourseDuration(
      [
        page('1', 1),
        page('2', 2),
        page('3', 3),
        { ...page('4'), type: 'quiz' },
        { ...page('5'), type: 'pbl' },
      ],
      1,
    );
    expect(planned.slice(0, 3).map((outline) => outline.estimatedDuration)).toEqual([10, 20, 30]);
    expect(planned.slice(3).every((outline) => !outline.durationBudget)).toBe(true);
  });

  it('passes the structured target and page budget to model prompts without removing reveal', () => {
    const requirements = withCourseDurationRequirement({
      requirement: 'C语言',
      targetDurationMinutes: 20,
    });
    expect(requirements.requirement).toContain('20 分钟');
    const planned = planCourseDuration([page('1')], 1)[0];
    const timed = withNarrationDuration(planned);
    expect(timed.description).toContain('60 秒');
    expect(timed.description).toContain('reveal');
    expect(timed.description).toContain('禁止用长时间静音');
    const visual = withSceneContentDuration(planned);
    expect(visual.description).toContain('60 秒');
    expect(visual.description).toContain('具体案例');
    expect(visual.description).toContain('可见且可指认');
    expect(visual.description).toContain('不能仅增加空泛的旁白');
  });

  it('reports measured audio separately from target, and rejects incomplete measurements', () => {
    expect(assessCourseDuration([scene(120)], 2, 1).status).toBe('within-tolerance');
    expect(assessCourseDuration([scene(60)], 2, 1).status).toBe('too-short');
    expect(assessCourseDuration([scene()], 2, 1).actualSeconds).toBeUndefined();
    expect(assessCourseDuration([scene(120)], 2, 2).status).toBe('unmeasured');
  });

  it('replaces the initial speaking-rate estimate with the measured narration length', () => {
    const planned = planCourseDuration([page('1')], 2)[0];
    planned.durationBudget = { targetSeconds: 104 };
    const corrected = withNarrationDuration(planned, {
      measuredSeconds: 86.12,
      targetSeconds: 104,
      narrationCharacters: 459,
      narrationWords: 100,
    });
    expect(corrected.description).toContain('中文约 554 字');
    expect(corrected.description).not.toContain('中文约 364 字');
    expect(corrected.description).toContain('上一版讲稿');
  });

  it('counts reveal as blocking and spotlight as nonblocking, and requires every audio clip', () => {
    const value = scene();
    value.actions = [
      { id: 'focus', type: 'spotlight', elementId: 'text' },
      { id: 'a', type: 'speech', text: '讲解', audioId: 'audio-a' },
      { id: 'r', type: 'reveal', elementId: 'text', duration: 520 },
    ];
    expect(measureScenePlaybackSeconds(value, { a: 12 })).toBe(12.52);
    expect(measureScenePlaybackSeconds(value, {})).toBeUndefined();
    value.actions.push({ id: 'v', type: 'play_video', elementId: 'video' });
    expect(measureScenePlaybackSeconds(value, { a: 12 })).toBeUndefined();
  });

  it('invalidates a measured result when the teacher edits narration', () => {
    const value = scene(120);
    value.actions = [{ id: 'a', type: 'speech', text: '原讲稿', audioId: 'audio-a' }];
    value.timing!.measurementKey = durationMeasurementKey(value);
    expect(assessCourseDuration([value], 2, 1).status).toBe('within-tolerance');
    if (value.actions[0].type === 'speech') value.actions[0].text = '改过的讲稿';
    expect(assessCourseDuration([value], 2, 1).status).toBe('unmeasured');
  });

  it('keeps measured duration when transport URLs become local asset references', () => {
    const original = scene(120);
    original.actions = [{ id: 'a', type: 'speech', text: '同一段讲解', audioId: 'tts_s1_a', audioUrl: 'https://teacher.example/audio.wav' } as never];
    original.timing!.measurementKey = durationMeasurementKey(original);
    const converted = { ...original, actions: [{ id: 'a', type: 'speech', text: '同一段讲解', audioId: 'ast_converted' }] } as Scene;
    expect(assessCourseDuration([converted], 2, 1).status).toBe('within-tolerance');
    converted.actions = [{ id: 'a', type: 'speech', text: '同一段讲解' }];
    expect(assessCourseDuration([converted], 2, 1).status).toBe('unmeasured');
  });

  it('keeps measurements across JSON object key reordering, including nested widget state', () => {
    const value = scene(120);
    value.actions = [
      { id: 'r', type: 'reveal', elementId: 'answer', effect: 'fade-up', duration: 520 },
      { id: 'w', type: 'widget_setState', state: { code: 'print(2)', result: { value: 2, ok: true } } },
      { id: 's', type: 'speech', text: '答案是2', audioId: 'a' },
    ];
    value.timing!.measurementKey = durationMeasurementKey(value);
    const restored = structuredClone(value);
    restored.actions = [
      { duration: 520, effect: 'fade-up', elementId: 'answer', type: 'reveal', id: 'r' },
      { state: { result: { ok: true, value: 2 }, code: 'print(2)' }, type: 'widget_setState', id: 'w' },
      { text: '答案是2', audioId: 'restored-a', type: 'speech', id: 's' },
    ];
    expect(durationMeasurementKey(restored)).toBe(value.timing!.measurementKey);
    expect(assessCourseDuration([restored], 2, 1).status).toBe('within-tolerance');
    restored.actions.reverse();
    expect(assessCourseDuration([restored], 2, 1).status).toBe('unmeasured');
  });

  it('recognizes saved pre-v2 teaching-plan reveal measurements after JSONB reorders fields', () => {
    const restored = scene(120);
    // Captured from the previous implementation before persistence reordered reveal fields.
    restored.timing!.measurementKey = '170:706129978';
    restored.actions = [
      { id: 'r', type: 'reveal', effect: 'fade-up', duration: 520, elementId: 'answer' },
      { id: 's', type: 'speech', text: '答案是2', audioId: 'restored-a' },
    ];
    expect(assessCourseDuration([restored], 2, 1).status).toBe('within-tolerance');
    for (const edit of [
      (actions: NonNullable<Scene['actions']>) => { if (actions[0].type === 'reveal') actions[0].duration = 900; },
      (actions: NonNullable<Scene['actions']>) => { if (actions[0].type === 'reveal') actions[0].elementId = 'other'; },
      (actions: NonNullable<Scene['actions']>) => { if (actions[1].type === 'speech') actions[1].text = '答案是3'; },
      (actions: NonNullable<Scene['actions']>) => { if (actions[1].type === 'speech') delete actions[1].audioId; },
      (actions: NonNullable<Scene['actions']>) => { if (actions[1].type === 'speech') actions[1].audioInvalidated = true; },
    ]) {
      const changed = structuredClone(restored);
      edit(changed.actions!);
      expect(assessCourseDuration([changed], 2, 1).status).toBe('unmeasured');
    }
  });
});

describe('measured narration calibration', () => {
  it('feeds the currently selected script length back to the next generation', async () => {
    const initial = scene(86.12);
    initial.timing!.plannedDurationSec = 104;
    initial.actions = [{ id: 'speech', type: 'speech', text: '字'.repeat(459) }];
    let feedbackSeen: unknown;
    await calibrateNarrationDuration(initial, {
      regenerate: async (feedback) => {
        feedbackSeen = feedback;
        return { ...scene(104), timing: { plannedDurationSec: 104, measuredDurationSec: 104 } };
      },
      dispose: async () => {},
    });
    expect(feedbackSeen).toMatchObject({
      measuredSeconds: 86.12, targetSeconds: 104, narrationCharacters: 459,
    });
  });

  it('corrects a short real measurement and disposes superseded audio', async () => {
    const initial = scene(60);
    const disposed: Scene[] = [];
    let attempts = 0;
    const result = await calibrateNarrationDuration(initial, {
      regenerate: async (feedback) => {
        attempts++;
        expect(feedback.measuredSeconds).toBe(60);
        return scene(120);
      },
      dispose: async (old) => {
        disposed.push(old);
      },
    });
    expect(result.timing?.measuredDurationSec).toBe(120);
    expect(attempts).toBe(1);
    expect(disposed).toEqual([initial]);
  });

  it('bounds paid retries and keeps the closest successful candidate', async () => {
    let attempts = 0;
    const result = await calibrateNarrationDuration(scene(60), {
      regenerate: async () => scene(++attempts === 1 ? 80 : 30),
      dispose: async () => {},
    });
    expect(attempts).toBe(2);
    expect(result.timing?.measuredDurationSec).toBe(80);
    expect(result.timing?.durationStatus).toBe('too-short');
  });

  it('does not call models without a complete measured audio duration', async () => {
    const result = await calibrateNarrationDuration(scene(), {
      regenerate: async () => {
        throw new Error('must not call model');
      },
      dispose: async () => {},
    });
    expect(result.timing?.durationStatus).toBe('unmeasured');
  });

  it('cleans allocated audio when calibration is cancelled', async () => {
    const initial = scene(60);
    const disposed: Scene[] = [];
    await expect(
      calibrateNarrationDuration(initial, {
        regenerate: async () => {
          throw new DOMException('cancelled', 'AbortError');
        },
        dispose: async (old) => {
          disposed.push(old);
        },
      }),
    ).rejects.toThrow('cancelled');
    expect(disposed).toEqual([initial]);
  });
});
