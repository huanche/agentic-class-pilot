import type { Slide } from '@openmaic/dsl';
import type { AgentInfo } from '@openmaic/generation';
import type {
  ImageMapping,
  PdfImage,
  SceneOutline,
  UserRequirements,
} from '@/lib/types/generation';
import type { Stage } from '@/lib/types/stage';
import type { TTSProviderId } from '@/lib/audio/types';

export interface CoursewareVoiceSelection {
  providerId: TTSProviderId;
  voice: string;
}

/** Serializable, credential-free handoff after the teacher confirms the outline. */
export interface BackgroundCoursewareInput {
  sessionId: string;
  stage: Stage;
  outlines: SceneOutline[];
  requirements: UserRequirements;
  agents: AgentInfo[];
  pdfImages?: PdfImage[];
  imageMapping?: ImageMapping;
  importedSlides?: Slide[];
  preferImportedCanvas?: boolean;
  narrationScripts?: string[];
  formulaEnhancedOrders?: number[];
  enableTTS: boolean;
  /** Snapshot the voice at submission; no provider credentials are included. */
  ttsVoice?: CoursewareVoiceSelection;
  enableMedia: boolean;
  enableImageGeneration?: boolean;
  enableVideoGeneration?: boolean;
}

export function isActiveCourseJob(status: string) {
  return status === 'queued' || status === 'running';
}

export const COURSE_JOB_STATUS_LABELS: Record<string, string> = {
  queued: '排队中',
  running: '生成中',
  review: '待审核',
  approved: '已审核',
  failed: '生成失败',
  cancelled: '已取消',
};
