import 'fake-indexeddb/auto';
import { afterEach, describe, expect, it } from 'vitest';
import { db } from '@/lib/utils/database';
import {
  buildInitialCourseGovernance,
  createAutomaticFallbackScene,
  evaluateCourseReleaseGate,
  setSceneReview,
} from '@/lib/course-governance/governance';
import type { CourseSourceFingerprint } from '@/lib/course-governance/contracts';
import type { PptContentDraft, SceneOutline } from '@/lib/types/generation';

const source: CourseSourceFingerprint = {
  algorithm: 'SHA-256',
  sha256: 'a'.repeat(64),
  fileName: 'lesson.pptx',
  mimeType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  byteLength: 1024,
  lastModified: 1,
  pageCount: 2,
  importedAt: 2,
};

const draft: PptContentDraft = {
  slides: [
    { id: 'source-1', originalIndex: 0, title: '分数', content: '理解分子和分母', speakerNotes: '', include: true },
    { id: 'source-2', originalIndex: 1, title: '练习', content: '比较两个分数', speakerNotes: '', include: true },
  ],
  revision: 1,
  updatedAt: 1,
};

const outlines: SceneOutline[] = [
  { id: 'outline-1', type: 'slide', title: '分数', description: '理解分子和分母', keyPoints: ['分子', '分母'], teachingObjective: '', estimatedDuration: 60, order: 1 },
  { id: 'outline-2', type: 'slide', title: '练习', description: '比较两个分数', keyPoints: ['比较'], teachingObjective: '', estimatedDuration: 60, order: 2 },
];

afterEach(async () => {
  await db.courseGovernance.clear();
});

describe('course governance', () => {
  it('maps faithful scenes to exact source pages and starts pending', () => {
    const record = buildInitialCourseGovernance({
      stageId: 'faithful-stage',
      mode: 'faithful',
      source,
      outlines,
      draft,
    });
    expect(record.sceneReviews.map((review) => review.sourceRefs[0].slideNumber)).toEqual([1, 2]);
    expect(record.sceneReviews.every((review) => review.state === 'pending')).toBe(true);
  });

  it('keeps enhanced scenes source-backed', () => {
    const record = buildInitialCourseGovernance({
      stageId: 'enhanced-stage',
      mode: 'learning-skills-enhanced',
      source,
      outlines,
      draft,
    });
    expect(record.sceneReviews.every((review) => review.sourceRefs.length > 0)).toBe(true);
  });

  it('keeps narration when a governed scene falls back', () => {
    const scene = createAutomaticFallbackScene({
      stageId: 'fallback-stage',
      outline: outlines[0],
      narrationScript: '这是根据第一页材料生成的简短讲解。',
    });
    expect(scene.actions).toEqual([
      expect.objectContaining({ type: 'speech', text: '这是根据第一页材料生成的简短讲解。' }),
    ]);
  });

  it('blocks release before review, passes after review, and invalidates edited scenes', async () => {
    const stageId = 'release-stage';
    const record = buildInitialCourseGovernance({
      stageId,
      mode: 'faithful',
      source,
      outlines: [outlines[0]],
      draft: { ...draft, slides: [draft.slides[0]] },
    });
    const scene = createAutomaticFallbackScene({ stageId, outline: outlines[0] });
    await db.courseGovernance.put(record);

    expect((await evaluateCourseReleaseGate(stageId, [scene])).ready).toBe(false);
    await setSceneReview({ stageId, scene, state: 'approved', reviewerNote: '已核验' });
    expect((await evaluateCourseReleaseGate(stageId, [scene])).ready).toBe(true);

    const edited = { ...scene, title: '审核后修改' };
    const gate = await evaluateCourseReleaseGate(stageId, [edited]);
    expect(gate.ready).toBe(false);
    expect(gate.reasons.some((reason) => reason.includes('重新审核'))).toBe(true);
  });
});
