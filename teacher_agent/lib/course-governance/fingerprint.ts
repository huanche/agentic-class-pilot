import type { Scene } from '@/lib/types/stage';
import type { CourseSourceFingerprint } from './contracts';

function bytesToHex(bytes: Uint8Array): string {
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
}

async function sha256Bytes(bytes: ArrayBuffer): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return bytesToHex(new Uint8Array(digest));
}

export async function fingerprintCoursewareFile(
  file: File,
  pageCount: number,
): Promise<CourseSourceFingerprint> {
  return {
    algorithm: 'SHA-256',
    sha256: await sha256Bytes(await file.arrayBuffer()),
    fileName: file.name,
    mimeType: file.type || 'application/octet-stream',
    byteLength: file.size,
    lastModified: file.lastModified,
    pageCount,
    importedAt: Date.now(),
  };
}

function stableSceneSnapshot(scene: Scene): string {
  return JSON.stringify({
    id: scene.id,
    outlineId: 'outlineId' in scene ? scene.outlineId : undefined,
    type: scene.type,
    title: scene.title,
    order: scene.order,
    content: scene.content,
    actions: scene.actions || [],
    whiteboards: scene.whiteboards || [],
  });
}

export async function fingerprintScene(scene: Scene): Promise<string> {
  return sha256Bytes(new TextEncoder().encode(stableSceneSnapshot(scene)).buffer);
}
