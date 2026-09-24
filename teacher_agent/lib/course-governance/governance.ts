import { nanoid } from 'nanoid';
import type { Slide } from '@openmaic/dsl';
import type { Scene } from '@/lib/types/stage';
import type { PptContentDraft, SceneOutline } from '@/lib/types/generation';
import type { CoursewareConversionMode } from '@/lib/learning-skills/courseware-mode';
import { db } from '@/lib/utils/database';
import { fingerprintScene } from './fingerprint';
import {
  COURSE_GOVERNANCE_SCHEMA_VERSION,
  type CourseDegradationRecord,
  type CourseGovernanceRecord,
  type CourseReleaseGateResult,
  type CourseSceneReview,
  type CourseSourceFingerprint,
  type CourseSourceReference,
  type SceneReviewState,
} from './contracts';

function tokens(value: string): Set<string> {
  return new Set(
    value
      .toLowerCase()
      .replace(/[^\p{L}\p{N}]+/gu, ' ')
      .split(/\s+/)
      .filter((token) => token.length > 1),
  );
}

function sourceRef(
  source: CourseSourceFingerprint,
  slide: PptContentDraft['slides'][number],
): CourseSourceReference {
  return {
    sourceSha256: source.sha256,
    slideNumber: slide.originalIndex + 1,
    sourceSlideId: slide.id,
    title: slide.title || undefined,
    excerpt: (slide.content || slide.speakerNotes || '').slice(0, 240) || undefined,
  };
}

export function inferSourceReferences(
  outline: SceneOutline,
  draft: PptContentDraft | undefined,
  source: CourseSourceFingerprint,
  mode: CoursewareConversionMode,
): CourseSourceReference[] {
  if (!draft) {
    return [
      {
        sourceSha256: source.sha256,
        slideNumber: mode === 'faithful' ? outline.order : 1,
        title: source.fileName,
        excerpt: outline.description?.slice(0, 240),
      },
    ];
  }
  const included = draft.slides.filter((slide) => slide.include);
  if (mode === 'faithful') {
    const exact = included[outline.order - 1];
    return exact ? [sourceRef(source, exact)] : [];
  }

  const query = tokens(
    [outline.title, outline.description, ...(outline.keyPoints || [])].filter(Boolean).join(' '),
  );
  const scored = included
    .map((slide) => {
      const haystack = tokens([slide.title, slide.content, slide.speakerNotes].join(' '));
      let score = 0;
      for (const token of query) if (haystack.has(token)) score += 1;
      return { slide, score };
    })
    .sort((a, b) => b.score - a.score || a.slide.originalIndex - b.slide.originalIndex);
  const matched = scored.filter((item) => item.score > 0).slice(0, 3);
  const selected = matched.length > 0 ? matched : scored.slice(0, Math.min(3, scored.length));
  return selected.map(({ slide }) => sourceRef(source, slide));
}

function detectSourceDegradations(
  slides: Slide[] | null,
  draft: PptContentDraft,
): CourseDegradationRecord[] {
  if (!slides) return [];
  const included = draft.slides.filter((slide) => slide.include);
  const records: CourseDegradationRecord[] = [];
  for (const [index, slideDraft] of included.entries()) {
    const slide = slides[slideDraft.originalIndex];
    if (!slide) continue;
    for (const element of slide.elements as Array<{ type?: string; src?: string; id?: string }>) {
      if (['chart', 'video', 'audio'].includes(element.type || '')) {
        records.push({
          id: nanoid(),
          sceneOrder: index + 1,
          kind: 'source-compatibility',
          severity: 'warning',
          status: 'fallback-applied',
          reason: `原 PPT 第 ${slideDraft.originalIndex + 1} 页包含 ${element.type} 元素；发布包保留原始画布作为静态回退。`,
          fallback: 'source-canvas',
          createdAt: Date.now(),
        });
      }
      if (element.src?.startsWith('blob:')) {
        records.push({
          id: nanoid(),
          sceneOrder: index + 1,
          kind: 'temporary-media',
          severity: 'blocker',
          status: 'unresolved',
          reason: `原 PPT 第 ${slideDraft.originalIndex + 1} 页包含仅当前标签页可用的临时媒体。`,
          fallback: 'none',
          createdAt: Date.now(),
        });
      }
    }
  }
  return records;
}

export function buildInitialCourseGovernance(input: {
  stageId: string;
  mode: CoursewareConversionMode;
  source: CourseSourceFingerprint;
  outlines: SceneOutline[];
  draft?: PptContentDraft;
  sourceSlides?: Slide[] | null;
}): CourseGovernanceRecord {
  const now = Date.now();
  return {
    stageId: input.stageId,
    schemaVersion: COURSE_GOVERNANCE_SCHEMA_VERSION,
    conversionMode: input.mode,
    source: input.source,
    sceneReviews: input.outlines.map((outline): CourseSceneReview => ({
      outlineId: outline.id,
      sceneOrder: outline.order,
      title: outline.title,
      sourceRefs: inferSourceReferences(outline, input.draft, input.source, input.mode),
      state: 'pending',
    })),
    degradations: input.draft
      ? detectSourceDegradations(input.sourceSlides || null, input.draft)
      : [],
    createdAt: now,
    updatedAt: now,
  };
}

export async function initializeCourseGovernance(
  input: Parameters<typeof buildInitialCourseGovernance>[0],
): Promise<CourseGovernanceRecord> {
  const existing = await db.courseGovernance.get(input.stageId);
  if (existing) return existing;
  const record = buildInitialCourseGovernance(input);
  await db.courseGovernance.put(record);
  return record;
}

export async function loadCourseGovernance(
  stageId: string,
): Promise<CourseGovernanceRecord | undefined> {
  return db.courseGovernance.get(stageId);
}

export async function setSceneReview(input: {
  stageId: string;
  scene: Scene;
  state: SceneReviewState;
  reviewerNote?: string;
}): Promise<CourseGovernanceRecord> {
  const record = await db.courseGovernance.get(input.stageId);
  if (!record) throw new Error('当前课程没有来源追踪记录，不能审核');
  const fingerprint = input.state === 'approved' ? await fingerprintScene(input.scene) : undefined;
  const reviews = record.sceneReviews.map((review) =>
    review.sceneOrder === input.scene.order
      ? {
          ...review,
          title: input.scene.title,
          state: input.state,
          reviewerNote: input.reviewerNote?.trim() || undefined,
          reviewedAt: Date.now(),
          reviewedSceneFingerprint: fingerprint,
        }
      : review,
  );
  const updated = { ...record, sceneReviews: reviews, updatedAt: Date.now() };
  await db.courseGovernance.put(updated);
  return updated;
}

export async function recordAutomaticFallback(input: {
  stageId: string;
  sceneOrder: number;
  kind: CourseDegradationRecord['kind'];
  reason: string;
  fallback: 'source-canvas' | 'text-slide';
}): Promise<void> {
  const record = await db.courseGovernance.get(input.stageId);
  if (!record) return;
  const degradation: CourseDegradationRecord = {
    id: nanoid(),
    sceneOrder: input.sceneOrder,
    kind: input.kind,
    severity: 'warning',
    status: 'fallback-applied',
    reason: input.reason,
    fallback: input.fallback,
    createdAt: Date.now(),
  };
  await db.courseGovernance.put({
    ...record,
    degradations: [...record.degradations, degradation],
    updatedAt: Date.now(),
  });
}

export function createAutomaticFallbackScene(input: {
  stageId: string;
  outline: SceneOutline;
  sourceSlide?: Slide;
  narrationScript?: string;
}): Scene {
  const internalInstruction =
    /reveal|独立文本元素|退出任务|形成性证据|Below\s*\/\s*At\s*\/\s*Above|自动降级|生成说明/iu;
  const description = internalInstruction.test(input.outline.description)
    ? ''
    : input.outline.description.trim();
  const points = (input.outline.keyPoints ?? [])
    .map((point) => point.trim())
    .filter((point) => point && !internalInstruction.test(point));
  const fallbackPoints = points.length > 0 ? points : [description || '请结合本页主题完成学习与思考。'];
  const escapeHtml = (value: string) =>
    value
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  const canvas: Slide =
    input.sourceSlide ||
    ({
      id: nanoid(),
      viewportSize: 1000,
      viewportRatio: 0.5625,
      theme: {
        backgroundColor: '#ffffff',
        themeColors: ['#2563eb', '#7c3aed', '#059669', '#ea580c', '#475569'],
        fontColor: '#0f172a',
        fontName: 'Microsoft YaHei',
        outline: { color: '#2563eb', width: 1, style: 'solid' },
        shadow: { h: 0, v: 4, blur: 16, color: '#00000022' },
      },
      elements: [
        {
          id: nanoid(),
          type: 'text',
          left: 80,
          top: 55,
          width: 840,
          height: 90,
          rotate: 0,
          defaultFontName: 'Microsoft YaHei',
          defaultColor: '#0f172a',
          content: `<h1>${escapeHtml(input.outline.title)}</h1>`,
        },
        ...(description
          ? [
              {
                id: nanoid(),
                type: 'text' as const,
                left: 90,
                top: 155,
                width: 820,
                height: 72,
                rotate: 0,
                defaultFontName: 'Microsoft YaHei',
                defaultColor: '#334155',
                content: `<p>${escapeHtml(description)}</p>`,
              },
            ]
          : []),
        ...fallbackPoints.slice(0, 5).map((point, index) => ({
          id: nanoid(),
          type: 'text' as const,
          left: 115,
          top: 235 + index * 62,
          width: 760,
          height: 52,
          rotate: 0,
          defaultFontName: 'Microsoft YaHei',
          defaultColor: '#0f172a',
          content: `<p><strong>${index + 1}.</strong> ${escapeHtml(point)}</p>`,
        })),
      ],
    } satisfies Slide);
  return {
    id: nanoid(),
    outlineId: input.outline.id,
    stageId: input.stageId,
    type: 'slide',
    title: input.outline.title,
    order: input.outline.order,
    content: { type: 'slide', canvas },
    actions: input.narrationScript
      ? [
          {
            id: `fallback-speech-${input.outline.id}`,
            type: 'speech',
            text: input.narrationScript,
          },
        ]
      : [],
    createdAt: Date.now(),
    updatedAt: Date.now(),
  };
}

export async function evaluateCourseReleaseGate(
  stageId: string,
  scenes: Scene[],
): Promise<CourseReleaseGateResult> {
  const record = await db.courseGovernance.get(stageId);
  if (!record) {
    return {
      applies: false,
      ready: true,
      reasons: [],
      approvedScenes: 0,
      totalScenes: scenes.length,
      unresolvedBlockers: 0,
    };
  }

  const reasons: string[] = [];
  if (!/^[a-f0-9]{64}$/i.test(record.source.sha256)) reasons.push('源文件 SHA-256 指纹缺失或无效');
  if (record.sceneReviews.length !== scenes.length) reasons.push('生成场景数量与来源追踪记录不一致');
  const sceneByOrder = new Map(scenes.map((scene) => [scene.order, scene]));
  const internalInstructionPattern =
    /利用独立文本元素|reveal 动画|退出任务收集|Below\s*\/\s*At\s*\/\s*Above|非忙碌型提前完成任务|形成性证据/iu;
  for (const scene of scenes) {
    if (scene.type !== 'slide' || scene.content.type !== 'slide') continue;
    const visibleText = scene.content.canvas.elements
      .filter((element) => element.type === 'text')
      .map((element) => element.content.replace(/<[^>]+>/g, ' '))
      .join(' ');
    if (internalInstructionPattern.test(visibleText)) {
      reasons.push(`场景 ${scene.order} 仍包含生成说明或占位内容，必须重新生成`);
    }
  }
  let approvedScenes = 0;
  for (const review of record.sceneReviews) {
    const scene = sceneByOrder.get(review.sceneOrder);
    if (!scene) {
      reasons.push(`第 ${review.sceneOrder} 个场景尚未生成`);
      continue;
    }
    if (review.sourceRefs.length === 0) reasons.push(`场景 ${review.sceneOrder} 缺少来源引用`);
    if (review.state !== 'approved' || !review.reviewedSceneFingerprint) {
      reasons.push(`场景 ${review.sceneOrder} 尚未审核通过`);
      continue;
    }
    const currentFingerprint = await fingerprintScene(scene);
    if (currentFingerprint !== review.reviewedSceneFingerprint) {
      reasons.push(`场景 ${review.sceneOrder} 在审核后已被修改，需要重新审核`);
      continue;
    }
    approvedScenes += 1;
  }
  const unresolvedBlockers = record.degradations.filter(
    (item) => item.severity === 'blocker' && item.status === 'unresolved',
  ).length;
  if (unresolvedBlockers > 0) reasons.push(`仍有 ${unresolvedBlockers} 个未解决的阻断级降级项`);

  return {
    applies: true,
    ready: reasons.length === 0,
    reasons: [...new Set(reasons)],
    approvedScenes,
    totalScenes: scenes.length,
    unresolvedBlockers,
  };
}

export async function assertCourseReleaseReady(stageId: string, scenes: Scene[]): Promise<void> {
  const gate = await evaluateCourseReleaseGate(stageId, scenes);
  if (gate.applies && !gate.ready) {
    throw new Error(`发布门禁未通过：${gate.reasons.slice(0, 3).join('；')}`);
  }
}
