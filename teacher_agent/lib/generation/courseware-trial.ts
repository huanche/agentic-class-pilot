import type { SpeechAction } from '@/lib/types/action';
import type { SceneOutline } from '@/lib/types/generation';

export function trialSpeechAudio(speech: SpeechAction) {
  return speech.audioInvalidated
    ? undefined
    : (speech as SpeechAction & { audioUrl?: string }).audioUrl;
}

export type LearningRequirement = NonNullable<SceneOutline['learningRequirement']>;

export const LESSON_REQUIREMENTS = {
  master: {
    label: '掌握',
    weight: 3,
    instruction: '解释原理，带学生做完一个完整例子，指出常见错误。',
  },
  familiar: { label: '熟悉', weight: 2, instruction: '解释用途和基本步骤，配一个简短示例。' },
  recognize: {
    label: '了解',
    weight: 1,
    instruction: '简要交代概念和适用情境，使学生能辨认、听得懂。',
  },
} satisfies Record<LearningRequirement, { label: string; weight: number; instruction: string }>;

export function trialLearningRequirement(value: unknown): LearningRequirement {
  return value === 'master' || value === 'recognize' ? value : 'familiar';
}

export function normalizeTrialOutlines(
  generated: SceneOutline[],
  faithfulSource?: SceneOutline[],
): SceneOutline[] {
  const sections = faithfulSource
    ? faithfulSource.map((source) => {
        const model =
          generated.find(
            (row) =>
              row.type === 'slide' &&
              typeof source.sourceSlideOriginalIndex === 'number' &&
              row.sourceSlideOriginalIndex === source.sourceSlideOriginalIndex,
          ) ??
          generated.find(
            (row) =>
              row.type === 'slide' &&
              row.sourceSlideOriginalIndex === undefined &&
              row.title.trim() === source.title.trim() &&
              faithfulSource.filter((page) => page.title.trim() === source.title.trim()).length ===
                1,
          );
        return {
          ...source,
          description: [source.description, model?.description].filter(Boolean).join('\n'),
          teachingObjective: model?.teachingObjective,
          learningRequirement: model?.learningRequirement,
          checkpoint: model?.checkpoint,
        };
      })
    : generated;
  return sections.map((section, index) => {
    const instruction =
      typeof section.checkpoint?.instruction === 'string'
        ? section.checkpoint.instruction.trim().slice(0, 500)
        : '';
    return {
      ...section,
      order: index + 1,
      learningRequirement: trialLearningRequirement(section.learningRequirement),
      checkpoint:
        instruction && ['slide', 'interactive'].includes(section.type)
          ? { instruction }
          : undefined,
      checkpointFor: undefined,
    };
  });
}

export function expandTrialCheckpoints(outlines: SceneOutline[]): SceneOutline[] {
  return outlines
    .flatMap((section): SceneOutline[] => {
      if (!section.checkpoint) return [section];
      return [
        section,
        {
          id: section.id + '-checkpoint',
          title: section.title + ' · 随堂题',
          description:
            '针对刚讲完的小节制作一道题。考查要求：' +
            section.checkpoint.instruction +
            '。判断题用单选题格式、两个选项。题干和选项不得透露答案，提交后用解析解释原因。\n' +
            section.description,
          keyPoints: section.keyPoints,
          type: 'quiz',
          order: 0,
          checkpointFor: section.id,
          quizConfig: { questionCount: 1, difficulty: 'easy', questionTypes: ['single'] },
        },
      ];
    })
    .map((page, index) => ({ ...page, order: index + 1 }));
}
