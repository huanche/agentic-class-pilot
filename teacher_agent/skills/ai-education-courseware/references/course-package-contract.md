# Governed course contract

Use this contract for persistence and release manifests. The source file remains immutable and is identified by its byte-level SHA-256.

```ts
interface SourceFingerprint {
  algorithm: 'SHA-256';
  sha256: string;
  fileName: string;
  mimeType: string;
  byteLength: number;
  lastModified: number;
  pageCount: number;
  importedAt: number;
}

interface SourceReference {
  sourceSha256: string;
  slideNumber: number;
  sourceSlideId?: string;
  title?: string;
  excerpt?: string;
}

interface SceneReview {
  outlineId: string;
  sceneOrder: number;
  title: string;
  sourceRefs: SourceReference[];
  state: 'pending' | 'approved' | 'rejected';
  reviewerNote?: string;
  reviewedAt?: number;
  reviewedSceneFingerprint?: string;
}

interface DegradationRecord {
  id: string;
  sceneOrder: number;
  kind: string;
  severity: 'info' | 'warning' | 'blocker';
  status: 'fallback-applied' | 'unresolved';
  reason: string;
  fallback: 'source-canvas' | 'text-slide' | 'none';
  createdAt: number;
}

interface CourseGovernanceRecord {
  stageId: string;
  schemaVersion: number;
  conversionMode: 'faithful' | 'learning-skills-enhanced';
  source: SourceFingerprint;
  sceneReviews: SceneReview[];
  degradations: DegradationRecord[];
  createdAt: number;
  updatedAt: number;
}
```

The exported manifest must include or accompany the same source version, conversion mode, scene/source mapping, review status, degradation list and release-gate result. Never mutate the source SHA-256 when a generated scene changes; scene versions use their own fingerprints.
