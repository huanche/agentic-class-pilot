import { describe, expect, it } from 'vitest';
import { expandTrialCheckpoints, normalizeTrialOutlines } from '@/lib/generation/courseware-trial';
import { planCourseDuration } from '@/lib/generation/course-duration';
import type { SceneOutline } from '@/lib/types/generation';

const source = [
  {
    id: 'definition',
    type: 'slide',
    title: '定义说明',
    description: '数组的长度',
    sourceSlideOriginalIndex: 4,
    keyPoints: [],
    order: 1,
  },
  {
    id: 'bounds',
    type: 'slide',
    title: '数组越界',
    description: '下标范围',
    sourceSlideOriginalIndex: 5,
    keyPoints: [],
    order: 2,
  },
] satisfies SceneOutline[];

describe('courseware trial', () => {
  it('keeps all source pages, applies teacher depth, and inserts the question after its section', () => {
    const generated: SceneOutline[] = [
      {
        ...source[1],
        learningRequirement: 'master',
        checkpoint: { instruction: '加一道越界判断题' },
      },
    ];
    const review = normalizeTrialOutlines(generated, source);
    expect(review.map((row) => [row.sourceSlideOriginalIndex, row.learningRequirement])).toEqual([
      [4, 'familiar'],
      [5, 'master'],
    ]);
    const planned = planCourseDuration(review, 1, true);
    expect(planned.map((row) => row.durationBudget?.targetSeconds)).toEqual([24, 36]);
    const pages = expandTrialCheckpoints(planned);
    expect(pages.map((row) => [row.id, row.type, row.order])).toEqual([
      ['definition', 'slide', 1],
      ['bounds', 'slide', 2],
      ['bounds-checkpoint', 'quiz', 3],
    ]);
    expect(pages[2]).toMatchObject({ checkpointFor: 'bounds', quizConfig: { questionCount: 1 } });
    expect(pages[2].description).toContain('越界判断题');
    expect(pages[2].durationBudget).toBeUndefined();
  });

  it('uses the teacher-selected level without auto-inserting a question', () => {
    const chosen = normalizeTrialOutlines([{ ...source[0], learningRequirement: 'master' }]);
    expect(expandTrialCheckpoints(chosen)).toHaveLength(1);
  });
});
