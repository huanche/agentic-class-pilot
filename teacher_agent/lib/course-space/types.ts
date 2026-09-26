export const DEFAULT_TEACHER_ID = 'local-teacher';

export type CourseSpaceStatus = 'draft' | 'active' | 'archived';
export type CourseKnowledgeNodeType =
  | 'course'
  | 'module'
  | 'lesson'
  | 'knowledge-point'
  | 'learning-objective'
  | 'activity'
  | 'assessment-item'
  | 'artifact-fragment'
  | 'source-chunk';
export type CourseKnowledgeRelationType =
  | 'contains'
  | 'prerequisite-of'
  | 'teaches'
  | 'targets'
  | 'supports'
  | 'assesses'
  | 'explains'
  | 'evidenced-by'
  | 'uses'
  | 'aligned-with';
export type MaterialStatus = 'uploaded' | 'parsing' | 'pending-review' | 'ready' | 'failed';
export type CourseArtifactType =
  | 'course-outline'
  | 'module-plan'
  | 'lesson-courseware'
  | 'narration'
  | 'exercise-set'
  | 'assessment-rubric'
  | 'pbl-project';

export type CourseLessonFileType =
  | 'lesson-objectives'
  | 'knowledge-points'
  | 'teaching-activities'
  | 'courseware-pages'
  | 'narration-segments'
  | 'exercises'
  | 'assessment-criteria';

export interface CourseLessonFile {
  id: string;
  lessonId: string;
  type: CourseLessonFileType;
  title: string;
  content: string;
  status: 'draft' | 'ready';
  classVisible?: boolean;
  classPublicationId?: string;
  classPublishedAt?: number;
  createdAt: number;
  updatedAt: number;
}

export interface CourseLesson {
  id: string;
  moduleId: string;
  title: string;
  order: number;
  objectives: string[];
  materialIds: string[];
  files?: CourseLessonFile[];
  createdAt: number;
  updatedAt: number;
}

export interface CourseModule {
  id: string;
  courseId: string;
  title: string;
  order: number;
  objectives: string[];
  lessons: CourseLesson[];
  createdAt: number;
  updatedAt: number;
}

export interface CourseMaterialRecord {
  id: string;
  teacherId: string;
  courseId: string;
  name: string;
  mimeType: string;
  size: number;
  storageKey: string;
  sha256?: string;
  status: MaterialStatus;
  pageCount?: number;
  parser?: string;
  error?: string;
  extractedAt?: number;
  createdAt: number;
  updatedAt: number;
  /** Explicit teacher-controlled visibility in the teaching class. */
  classVisible?: boolean;
  activatedAt?: number;
  /** Immutable identifier assigned when this material is first published to Class. */
  classPublicationId?: string;
  classPublishedAt?: number;
}

export interface CourseStudentLearningState {
  studentId: string;
  name: string;
  studentNumber?: string;
  className?: string;
  status: 'not-started' | 'learning' | 'completed' | 'needs-attention';
  progress: number;
  completedResourceIds: string[];
  lastActiveAt?: number;
  /** 平台学情明细（学生 Agent 同步，选填）。 */
  learnedLessons?: number;
  totalLessons?: number;
  sessionCount?: number;
  endedCount?: number;
  stars?: number;
}

export interface CourseSpace {
  id: string;
  teacherId: string;
  title: string;
  subject?: string;
  gradeBand?: string;
  term?: string;
  description?: string;
  status: CourseSpaceStatus;
  modules: CourseModule[];
  materials: CourseMaterialRecord[];
  activeKnowledgePackageId?: string;
  activeKnowledgeGraphVersion?: number;
  curriculum?: {
    totalWeeks: number;
    lessonsPerWeek: number;
    lessonDurationMinutes?: number;
    baselineVersion?: number;
  };
  classStudents?: CourseStudentLearningState[];
  createdAt: number;
  updatedAt: number;
}

export interface CourseKnowledgeEvidence {
  id: string;
  courseId: string;
  graphVersion: number;
  nodeId: string;
  materialId: string;
  chunkId: string;
  page?: number;
  slide?: number;
  sourceSha256: string;
  excerpt?: string;
}

export interface CourseKnowledgeNode {
  id: string;
  courseId: string;
  graphVersion: number;
  type: CourseKnowledgeNodeType;
  title: string;
  description?: string;
  moduleId?: string;
  lessonId?: string;
  status: 'extracted' | 'reviewed' | 'approved';
  properties: Record<string, unknown>;
  evidence: CourseKnowledgeEvidence[];
  createdAt: number;
  updatedAt: number;
}

export interface CourseKnowledgeEdge {
  id: string;
  courseId: string;
  graphVersion: number;
  sourceNodeId: string;
  targetNodeId: string;
  type: CourseKnowledgeRelationType;
  properties: Record<string, unknown>;
  createdAt: number;
}

export interface CourseKnowledgeGraph {
  courseId: string;
  version: number;
  status: 'draft' | 'review' | 'published' | 'superseded';
  title: string;
  summary?: string;
  nodes: CourseKnowledgeNode[];
  edges: CourseKnowledgeEdge[];
  sourceMaterialHashes: string[];
  createdBy: string;
  createdAt: number;
  publishedAt?: number;
}

export type CourseKnowledgeExtractionPhase =
  | 'queued'
  | 'retrieving'
  | 'extracting'
  | 'merging'
  | 'aligning'
  | 'persisting'
  | 'review';

export interface CourseKnowledgeExtractionJob {
  id: string;
  teacherId: string;
  courseId: string;
  graphVersion: number;
  sessionId: string;
  status: 'queued' | 'running' | 'review' | 'failed';
  phase: CourseKnowledgeExtractionPhase;
  progress: number;
  message: string;
  extractedKnowledgeCount?: number;
  extractedObjectiveCount?: number;
  error?: string;
  createdAt: number;
  updatedAt: number;
}

export interface CourseAccessGrant {
  id: string;
  tenantId: string;
  courseId: string;
  subjectType: 'teacher' | 'student' | 'class' | 'service';
  subjectId: string;
  role: 'owner' | 'editor' | 'reviewer' | 'reader';
  createdAt: number;
  expiresAt?: number;
}

export interface CreateCourseSpaceInput {
  /** Platform-initiated creation passes the platform course UUID. */
  id?: string;
  teacherId: string;
  title: string;
  subject?: string;
  gradeBand?: string;
  term?: string;
  description?: string;
}

export interface CourseArtifactJob {
  id: string;
  teacherId: string;
  courseId: string;
  scope:
    | { type: 'course' }
    | { type: 'module'; moduleId: string }
    | { type: 'lesson'; lessonId: string };
  artifactType: CourseArtifactType;
  status: 'queued' | 'running' | 'review' | 'approved' | 'failed';
  progress: number;
  message: string;
  artifactId?: string;
  knowledgePackageId?: string;
  error?: string;
  createdAt: number;
  updatedAt: number;
}

export interface CourseMaterialChunk {
  id: string;
  materialId: string;
  page: number;
  text: string;
}

export interface CourseMaterialExtraction {
  materialId: string;
  courseId: string;
  sourceSha256: string;
  text: string;
  pageCount: number;
  parser?: string;
  chunks: CourseMaterialChunk[];
  formulas: Array<{ page: number; latex: string }>;
  createdAt: number;
}

export interface CourseArtifactRecord {
  id: string;
  jobId: string;
  teacherId: string;
  courseId: string;
  scope: CourseArtifactJob['scope'];
  type: CourseArtifactType;
  title: string;
  content: string;
  /** Sanitized display HTML generated from the canonical Markdown content. */
  htmlContent?: string;
  /** Server-side Word derivative for downloadable teaching documents. */
  wordFileName?: string;
  wordStorageKey?: string;
  status: 'review' | 'approved' | 'published';
  citations: PublishedKnowledgeCitation[];
  classroomId?: string;
  classroomUrl?: string;
  reviewerNote?: string;
  approvedAt?: number;
  createdAt: number;
  updatedAt: number;
  /** Explicit teacher-controlled visibility in the teaching class. */
  classVisible?: boolean;
  activatedAt?: number;
  /** Immutable identifier assigned when this artifact is first published to Class. */
  classPublicationId?: string;
  classPublishedAt?: number;
}

export interface PublishedKnowledgeCitation {
  materialId: string;
  sourceName: string;
  page?: number;
  slide?: number;
  sourceSha256: string;
}

export interface PublishedKnowledgeEntry {
  id: string;
  courseId: string;
  moduleId?: string;
  lessonId?: string;
  title: string;
  content: string;
  citations: PublishedKnowledgeCitation[];
  approvedAt: number;
}

export interface PublishedKnowledgePackage {
  id: string;
  teacherId: string;
  courseId: string;
  version: number;
  status: 'draft' | 'published' | 'superseded';
  entries: PublishedKnowledgeEntry[];
  createdAt: number;
  publishedAt?: number;
}
