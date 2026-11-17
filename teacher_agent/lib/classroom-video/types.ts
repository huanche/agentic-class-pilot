import type { Scene, Stage } from '@/lib/types/stage';
import type { VideoCaption } from './captions';

export interface VideoClipPlan {
  sceneId: string;
  key: string;
  audio: Record<string, { file: string; sha256: string }>;
}
export interface ClassroomVideoPlan {
  schema: 1;
  id: string;
  version: string;
  ownerId: string;
  createdAt: number;
  stage: Stage;
  scenes: Scene[];
  clips: VideoClipPlan[];
}
export type ClassroomVideoPhase = 'loading' | 'recording' | 'encoding';

export interface ClassroomVideoStatus {
  version: string;
  state: 'queued' | 'rendering' | 'failed' | 'ready';
  phase?: ClassroomVideoPhase;
  activePages?: Record<string, ClassroomVideoPhase>;
  completed: number;
  total: number;
  error?: string;
  currentSceneId?: string;
  readySceneIds?: string[];
  failedPages?: Record<string, string>;
  updatedAt: number;
}
export interface ClassroomVideoManifest {
  version: string;
  title: string;
  status: ClassroomVideoStatus;
  stage: Stage;
  scenes: Scene[];
  clips: { sceneId: string; url: string; captions?: VideoCaption[] }[];
}
