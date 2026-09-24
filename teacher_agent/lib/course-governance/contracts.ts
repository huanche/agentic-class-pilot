import type { CoursewareConversionMode } from '@/lib/learning-skills/courseware-mode';

export const COURSE_GOVERNANCE_SCHEMA_VERSION = 1;

export interface CourseSourceFingerprint {
  algorithm: 'SHA-256';
  sha256: string;
  fileName: string;
  mimeType: string;
  byteLength: number;
  lastModified: number;
  pageCount: number;
  importedAt: number;
}

export interface CourseSourceReference {
  sourceSha256: string;
  slideNumber: number;
  sourceSlideId?: string;
  title?: string;
  excerpt?: string;
}

export type SceneReviewState = 'pending' | 'approved' | 'rejected';

export interface CourseSceneReview {
  outlineId: string;
  sceneOrder: number;
  title: string;
  sourceRefs: CourseSourceReference[];
  state: SceneReviewState;
  reviewerNote?: string;
  reviewedAt?: number;
  reviewedSceneFingerprint?: string;
}

export type DegradationSeverity = 'info' | 'warning' | 'blocker';
export type DegradationStatus = 'fallback-applied' | 'unresolved';

export interface CourseDegradationRecord {
  id: string;
  sceneOrder: number;
  kind:
    | 'source-compatibility'
    | 'temporary-media'
    | 'content-generation-failure'
    | 'action-generation-failure'
    | 'tts-generation-failure'
    | 'missing-source-reference';
  severity: DegradationSeverity;
  status: DegradationStatus;
  reason: string;
  fallback: 'source-canvas' | 'text-slide' | 'none';
  createdAt: number;
}

export interface CourseGovernanceRecord {
  stageId: string;
  schemaVersion: number;
  conversionMode: CoursewareConversionMode;
  source: CourseSourceFingerprint;
  sceneReviews: CourseSceneReview[];
  degradations: CourseDegradationRecord[];
  createdAt: number;
  updatedAt: number;
}

export interface CourseReleaseGateResult {
  applies: boolean;
  ready: boolean;
  reasons: string[];
  approvedScenes: number;
  totalScenes: number;
  unresolvedBlockers: number;
}
