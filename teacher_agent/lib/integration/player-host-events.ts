import { postSaasHostMessage } from './host-bridge';

export type PlayerHostEvent = 'SCENE_COMPLETED' | 'PLAYBACK_ENDED';

function classroomIdFromPath() {
  if (typeof window === 'undefined') return undefined;
  const match = window.location.pathname.match(/\/(?:classroom-player|classroom)\/([^/]+)/);
  return match ? decodeURIComponent(match[1]) : undefined;
}

export function postPlayerHostEvent(type: PlayerHostEvent, sceneId?: string) {
  const classroomId = classroomIdFromPath();
  if (!classroomId) return false;
  return postSaasHostMessage(type, {
    classroomId,
    sceneId,
    eventId: globalThis.crypto?.randomUUID?.() ?? `player-${Date.now()}`,
  });
}
