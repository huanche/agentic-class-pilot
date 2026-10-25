import 'fake-indexeddb/auto';
import { afterEach, expect, it } from 'vitest';
import type { GenerationSessionState } from '@/app/generation-preview/types';
import { ensureCoursewareSourceFingerprint } from '@/lib/course-space/source-fingerprint';
import { initializeCourseGovernance } from '@/lib/course-governance/governance';
import { db } from '@/lib/utils/database';
import { planCourseDuration } from '@/lib/generation/course-duration';

afterEach(() => db.courseGovernance.clear());

const session = (): GenerationSessionState => ({
  sessionId: 'saved-failed-session',
  requirements: { requirement: '生成五页，以幻灯片为主', targetDurationMinutes: 6 },
  pdfText: '【第一份.pdf】\nwhile先判断条件\n\n【第二份.PPT】\ndo-while至少执行一次',
  conversionMode: 'learning-skills-enhanced',
  sourceType: 'learning-skills-enhanced',
  currentStep: 'generating',
  previewPhase: 'generating-content',
  courseSpaceContext: {
    courseId: 'course',
    materialIds: ['pdf', 'ppt'],
    scope: { type: 'course' },
  },
  sceneOutlines: [
    { id: 'page', type: 'slide', order: 1, title: '循环', description: '比较循环', keyPoints: [] },
  ],
});

it('repairs a saved failed document session without discarding its outline or teacher choices', async () => {
  const old = session();
  const fixed = await ensureCoursewareSourceFingerprint(old);
  expect(fixed.sourceFingerprint).toMatchObject({
    algorithm: 'SHA-256',
    mimeType: 'application/json',
  });
  expect(fixed.sourceFingerprint?.sha256).toMatch(/^[a-f0-9]{64}$/);
  expect(fixed.sceneOutlines).toBe(old.sceneOutlines);
  expect(fixed.requirements).toBe(old.requirements);
  expect(fixed.pdfText).toBe(old.pdfText);
  expect(fixed.previewPhase).toBe('generating-content');
  expect(await ensureCoursewareSourceFingerprint(fixed)).toBe(fixed);
});

it('passes the original required source gate and persists governance for all five mixed pages', async () => {
  const fixed = await ensureCoursewareSourceFingerprint(session());
  if (!fixed.sourceFingerprint) throw new Error('来源指纹缺失');
  const outlines = (['slide', 'slide', 'slide', 'interactive', 'quiz'] as const).map((type, i) => ({
    id: `page-${i + 1}`,
    type,
    order: i + 1,
    title: `循环第${i + 1}页`,
    description: '依据所选材料解释循环',
    keyPoints: ['条件与更新'],
  }));
  await initializeCourseGovernance({
    stageId: 'repaired-five-page-stage',
    mode: fixed.conversionMode!,
    source: fixed.sourceFingerprint,
    outlines,
  });
  const saved = await db.courseGovernance.get('repaired-five-page-stage');
  expect(saved?.sceneReviews).toHaveLength(5);
  expect(
    saved?.sceneReviews.every(
      (page) => page.sourceRefs[0].sourceSha256 === fixed.sourceFingerprint!.sha256,
    ),
  ).toBe(true);
});

it('keeps only the five retained pages after deletion, reindexes them and replans the six-minute budget', async () => {
  const original = session();
  const pages = (['slide', 'slide', 'slide', 'slide', 'slide', 'interactive', 'quiz'] as const).map(
    (type, i) => ({
      id: `original-${i + 1}`,
      type,
      order: i + 1,
      title: `第${i + 1}页`,
      description: '解释循环边界',
      keyPoints: [],
      estimatedDuration: 60,
    }),
  );
  const retained = pages.filter((page) => !['original-2', 'original-4'].includes(page.id));
  const edited = {
    ...original,
    sceneOutlines: planCourseDuration(
      retained.map((page, i) => ({ ...page, order: i + 1 })),
      original.requirements.targetDurationMinutes!,
    ),
  };
  const fixed = await ensureCoursewareSourceFingerprint(edited);
  expect(fixed.sceneOutlines).toBe(edited.sceneOutlines);
  expect(fixed.sceneOutlines?.map((page) => page.id)).toEqual([
    'original-1',
    'original-3',
    'original-5',
    'original-6',
    'original-7',
  ]);
  expect(fixed.sceneOutlines?.map((page) => page.order)).toEqual([1, 2, 3, 4, 5]);
  expect(fixed.sceneOutlines?.map((page) => page.type)).toEqual([
    'slide',
    'slide',
    'slide',
    'interactive',
    'quiz',
  ]);
  expect(
    fixed.sceneOutlines?.reduce((sum, page) => sum + (page.durationBudget?.targetSeconds ?? 0), 0),
  ).toBe(360);
  expect(fixed.sourceFingerprint?.sha256).toBe(
    (await ensureCoursewareSourceFingerprint(original)).sourceFingerprint?.sha256,
  );
  expect(fixed.pdfText).toBe(original.pdfText);
});

it('hashes every selected source and its content, but not an edited overview or generation requirements', async () => {
  const original = session();
  const sha = (await ensureCoursewareSourceFingerprint(original)).sourceFingerprint!.sha256;
  expect(
    (
      await ensureCoursewareSourceFingerprint({
        ...original,
        lessonOverview: '改用工程案例',
        requirements: { ...original.requirements, targetDurationMinutes: 10 },
      })
    ).sourceFingerprint?.sha256,
  ).toBe(sha);
  expect(
    (
      await ensureCoursewareSourceFingerprint({
        ...original,
        pdfText: original.pdfText + '\n第三份内容',
      })
    ).sourceFingerprint?.sha256,
  ).not.toBe(sha);
  expect(
    (
      await ensureCoursewareSourceFingerprint({
        ...original,
        courseSpaceContext: { ...original.courseSpaceContext!, materialIds: ['pdf', 'other'] },
      })
    ).sourceFingerprint?.sha256,
  ).not.toBe(sha);
});

it('never substitutes an extracted snapshot for a faithful or PPTX canvas fingerprint', async () => {
  for (const protectedSession of [
    { ...session(), conversionMode: 'faithful' as const },
    { ...session(), pptxImportStorageKey: 'original-canvas' },
    { ...session(), pdfText: '' },
    { ...session(), courseSpaceContext: undefined },
    { ...session(), courseSpaceContext: { ...session().courseSpaceContext!, materialIds: [] } },
  ]) {
    expect(await ensureCoursewareSourceFingerprint(protectedSession)).toBe(protectedSession);
    expect(protectedSession.sourceFingerprint).toBeUndefined();
  }
});
