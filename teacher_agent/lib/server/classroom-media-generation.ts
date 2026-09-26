/**
 * Server-side media and TTS generation for classrooms.
 *
 * Generates image/video files and TTS audio for a classroom,
 * writes them to disk, and returns serving URL mappings.
 */

import { promises as fs } from 'fs';
import path from 'path';
import { createHash } from 'crypto';
import { createLogger } from '@/lib/logger';
import { CLASSROOMS_DIR } from '@/lib/server/classroom-storage';
import { generateImage } from '@/lib/media/image-providers';
import { generateVideo, normalizeVideoOptions } from '@/lib/media/video-providers';
import { generateTTS } from '@/lib/audio/tts-providers';
import { DEFAULT_TTS_VOICES, DEFAULT_TTS_MODELS, TTS_PROVIDERS } from '@/lib/audio/constants';
import { IMAGE_PROVIDERS } from '@/lib/media/image-providers';
import { VIDEO_PROVIDERS } from '@/lib/media/video-providers';
import {
  getServerImageProviders,
  getServerVideoProviders,
  getServerTTSProviders,
  resolveImageApiKey,
  resolveImageBaseUrl,
  resolveVideoApiKey,
  resolveVideoBaseUrl,
  resolveTTSApiKey,
  resolveTTSBaseUrl,
} from '@/lib/server/provider-config';
import type { SceneOutline } from '@/lib/types/generation';
import type { Scene } from '@/lib/types/stage';
import type { SpeechAction } from '@/lib/types/action';
import type { ImageProviderId } from '@/lib/media/types';
import type { VideoProviderId } from '@/lib/media/types';
import type { TTSProviderId } from '@/lib/audio/types';
import {
  filterUnspeakableSpeechActions,
  splitLongSpeechActions,
} from '@/lib/audio/tts-utils';
import { isGeneratedMediaPlaceholder } from '@/lib/media/media-ref';
import { VOXCPM_AUTO_VOICE_ID, VOXCPM_TTS_PROVIDER_ID } from '@/lib/audio/voxcpm';
import { type PlatformTtsConfig } from '@/lib/server/platform-user-model-config';

const log = createLogger('ClassroomMedia');

/**
 * The classroom JSON payload is a pre-conversion transport, not a persisted
 * DSL document. `audioUrl` is gone from the `SpeechAction` contract, but the
 * file-based classroom store has no asset registry to allocate from, so the
 * server still hands the client the serving URL beside the derived `audioId`.
 * The app-side reference converter ingests the URL's bytes and rewrites the
 * pair to one allocated asset id when the classroom is first fetched, before
 * the document is persisted client-side; the URL never enters a stored
 * document.
 */
type ServerTransportSpeechAction = SpeechAction & { audioUrl?: string };

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function ensureDir(dir: string) {
  await fs.mkdir(dir, { recursive: true });
}

const DOWNLOAD_TIMEOUT_MS = 120_000; // 2 minutes
const DOWNLOAD_MAX_SIZE = 100 * 1024 * 1024; // 100 MB

async function downloadToBuffer(url: string): Promise<Buffer> {
  const resp = await fetch(url, { signal: AbortSignal.timeout(DOWNLOAD_TIMEOUT_MS) });
  if (!resp.ok) throw new Error(`Download failed: ${resp.status} ${resp.statusText}`);
  const contentLength = Number(resp.headers.get('content-length') || 0);
  if (contentLength > DOWNLOAD_MAX_SIZE) {
    throw new Error(`File too large: ${contentLength} bytes (max ${DOWNLOAD_MAX_SIZE})`);
  }
  return Buffer.from(await resp.arrayBuffer());
}

function mediaServingUrl(baseUrl: string, classroomId: string, subPath: string): string {
  return `${baseUrl}/api/classroom-media/${classroomId}/${subPath}`;
}

// ---------------------------------------------------------------------------
// Image / Video generation
// ---------------------------------------------------------------------------

export async function generateMediaForClassroom(
  outlines: SceneOutline[],
  classroomId: string,
  baseUrl: string,
): Promise<Record<string, string>> {
  const mediaDir = path.join(CLASSROOMS_DIR, classroomId, 'media');
  await ensureDir(mediaDir);

  // Collect all media generation requests from outlines
  const requests = outlines.flatMap((o) => o.mediaGenerations ?? []);
  if (requests.length === 0) return {};

  // Resolve providers
  const serverImageProviders = getServerImageProviders();
  // Qwen is the platform's verified teaching-image provider. Prefer it over a
  // stale OpenAI-compatible entry, while retaining provider fallback.
  const imageProviderIds = Object.keys(serverImageProviders).sort((a, b) =>
    a === 'qwen-image' ? -1 : b === 'qwen-image' ? 1 : 0,
  );
  const videoProviderIds = Object.keys(getServerVideoProviders());

  const mediaMap: Record<string, string> = {};

  // Separate image and video requests, generate each type sequentially
  // but run the two types in parallel (providers often have limited concurrency).
  const imageRequests = requests.filter((r) => r.type === 'image' && imageProviderIds.length > 0);
  const videoRequests = requests.filter((r) => r.type === 'video' && videoProviderIds.length > 0);

  const generateImages = async () => {
    for (const req of imageRequests) {
      let generated = false;
      for (const candidate of imageProviderIds) {
        try {
          const providerId = candidate as ImageProviderId;
          const apiKey = resolveImageApiKey(providerId);
          const providerConfig = IMAGE_PROVIDERS[providerId];
          if (providerConfig?.requiresApiKey && !apiKey) {
            log.warn(`No API key for image provider "${providerId}", skipping ${req.elementId}`);
            continue;
          }
          const model =
            serverImageProviders[providerId]?.models?.[0] || providerConfig?.models?.[0]?.id;

          const result = await generateImage(
            { providerId, apiKey, baseUrl: resolveImageBaseUrl(providerId), model },
            { prompt: req.prompt, aspectRatio: req.aspectRatio || '16:9' },
          );

          let buf: Buffer;
          let ext: string;
          if (result.base64) {
            buf = Buffer.from(result.base64, 'base64');
            ext = 'png';
          } else if (result.url) {
            buf = await downloadToBuffer(result.url);
            const urlExt = path.extname(new URL(result.url).pathname).replace('.', '');
            ext = ['png', 'jpg', 'jpeg', 'webp'].includes(urlExt) ? urlExt : 'png';
          } else {
            throw new Error('Image generation returned no data');
          }

          const filename = `${req.elementId}.${ext}`;
          await fs.writeFile(path.join(mediaDir, filename), buf);
          mediaMap[req.elementId] = mediaServingUrl(baseUrl, classroomId, `media/${filename}`);
          log.info(`Generated image with ${providerId}: ${filename}`);
          generated = true;
          break;
        } catch (err) {
          log.warn(`Image generation failed for ${req.elementId} with ${candidate}:`, err);
        }
      }
      if (!generated) {
        log.warn(`All image providers failed for ${req.elementId}`);
      }
    }
  };

  const generateVideos = async () => {
    for (const req of videoRequests) {
      try {
        const providerId = videoProviderIds[0] as VideoProviderId;
        const apiKey = resolveVideoApiKey(providerId);
        if (!apiKey) {
          log.warn(`No API key for video provider "${providerId}", skipping ${req.elementId}`);
          continue;
        }
        const providerConfig = VIDEO_PROVIDERS[providerId];
        const model = providerConfig?.models?.[0]?.id;

        const normalized = normalizeVideoOptions(providerId, {
          prompt: req.prompt,
          aspectRatio: (req.aspectRatio as '16:9' | '4:3' | '1:1' | '9:16') || '16:9',
        });

        const result = await generateVideo(
          { providerId, apiKey, baseUrl: resolveVideoBaseUrl(providerId), model },
          normalized,
        );

        const buf = await downloadToBuffer(result.url);
        const filename = `${req.elementId}.mp4`;
        await fs.writeFile(path.join(mediaDir, filename), buf);
        mediaMap[req.elementId] = mediaServingUrl(baseUrl, classroomId, `media/${filename}`);
        log.info(`Generated video: ${filename}`);
      } catch (err) {
        log.warn(`Video generation failed for ${req.elementId}:`, err);
      }
    }
  };

  await Promise.all([generateImages(), generateVideos()]);

  return mediaMap;
}

// ---------------------------------------------------------------------------
// Placeholder replacement in scene content
// ---------------------------------------------------------------------------

export function replaceMediaPlaceholders(scenes: Scene[], mediaMap: Record<string, string>): void {
  if (Object.keys(mediaMap).length === 0) return;

  for (const scene of scenes) {
    if (scene.type !== 'slide') continue;
    const canvas = (
      scene.content as {
        canvas?: {
          elements?: Array<{ id: string; src?: string; mediaRef?: string; type?: string }>;
        };
      }
    )?.canvas;
    if (!canvas?.elements) continue;

    for (const el of canvas.elements) {
      if (
        el.type === 'video' &&
        typeof el.mediaRef === 'string' &&
        mediaMap[el.mediaRef] &&
        (!el.src || /^gen_vid_[\w-]+$/i.test(el.src))
      ) {
        el.src = mediaMap[el.mediaRef];
        continue;
      }
      if (
        (el.type === 'image' || el.type === 'video') &&
        typeof el.src === 'string' &&
        isGeneratedMediaPlaceholder(el.src) &&
        mediaMap[el.src]
      ) {
        el.src = mediaMap[el.src];
      }
    }
  }
}

// Some Qwen streaming WAV responses use sentinel RIFF/data sizes. Browsers may
// reject the otherwise valid PCM bytes, so finalize the header before storage.
function finalizeWav(audio: Buffer): Buffer {
  if (audio.length < 44 || audio.toString('ascii', 0, 4) !== 'RIFF' ||
      audio.toString('ascii', 8, 12) !== 'WAVE') return audio;
  let offset = 12;
  while (offset + 8 <= audio.length) {
    const chunkSize = audio.readUInt32LE(offset + 4);
    if (audio.toString('ascii', offset, offset + 4) === 'data') {
      const fixed = Buffer.from(audio);
      fixed.writeUInt32LE(fixed.length - 8, 4);
      fixed.writeUInt32LE(fixed.length - offset - 8, offset + 4);
      return fixed;
    }
    const next = offset + 8 + chunkSize + (chunkSize % 2);
    if (next <= offset || next > audio.length) break;
    offset = next;
  }
  return audio;
}

// ---------------------------------------------------------------------------
// TTS generation
// ---------------------------------------------------------------------------

export async function generateTTSForClassroom(
  scenes: Scene[],
  classroomId: string,
  baseUrl: string,
  ttsOverride?: PlatformTtsConfig | null,
): Promise<{ generated: number; failed: number; skipped: number }> {
  const audioDir = path.join(CLASSROOMS_DIR, classroomId, 'audio');
  await ensureDir(audioDir);

  // Resolve TTS provider — platform BYOK override first (per-user config),
  // then server-managed providers (exclude browser-native-tts and operator
  // force-disabled providers — server precedence, #665).
  let providerId: TTSProviderId;
  let apiKey: string;
  let byokModel: string | undefined;
  let byokVoice: string | undefined;
  if (ttsOverride?.apiKey) {
    const requested = (ttsOverride.provider || '') as TTSProviderId;
    if (TTS_PROVIDERS[requested as keyof typeof TTS_PROVIDERS]) {
      providerId = requested;
    } else {
      log.warn(`BYOK TTS provider "${ttsOverride.provider ?? "?"}" unknown, falling back to qwen-tts`);
      providerId = "qwen-tts" as TTSProviderId;
    }
    apiKey = ttsOverride.apiKey;
    byokModel = ttsOverride.model || undefined;
    byokVoice = ttsOverride.voice || undefined;
  } else {
    const ttsProviderIds = Object.entries(getServerTTSProviders())
      .filter(([id, info]) => id !== "browser-native-tts" && !info.disabled)
      .map(([id]) => id);
    if (ttsProviderIds.length === 0) {
      log.warn("No server TTS provider configured, skipping TTS generation");
      return { generated: 0, failed: 0, skipped: 1 };
    }
    providerId = ttsProviderIds[0] as TTSProviderId;
    apiKey = resolveTTSApiKey(providerId);
  }
  const ttsProvider = TTS_PROVIDERS[providerId as keyof typeof TTS_PROVIDERS];
  if (ttsProvider?.requiresApiKey && !apiKey) {
    log.warn(`No API key for TTS provider "${providerId}", skipping TTS generation`);
    return { generated: 0, failed: 0, skipped: 1 };
  }
  const ttsBaseUrl =
    (ttsOverride?.apiKey ? ttsOverride.baseUrl || undefined : resolveTTSBaseUrl(providerId)) ||
    ttsProvider?.defaultBaseUrl;
  const voice =
    byokVoice || DEFAULT_TTS_VOICES[providerId as keyof typeof DEFAULT_TTS_VOICES] || "default";
  const format = ttsProvider?.supportedFormats?.[0] || 'mp3';
  if (providerId === VOXCPM_TTS_PROVIDER_ID && voice === VOXCPM_AUTO_VOICE_ID) {
    log.warn('VoxCPM Auto Voice requires agent context; skipping server-side TTS generation');
    return { generated: 0, failed: 0, skipped: 1 };
  }

  let generated = 0;
  let failed = 0;
  let skipped = 0;

  for (const scene of scenes) {
    if (!scene.actions) continue;

    // Split long speech actions into multiple shorter ones before TTS generation,
    // mirroring the client-side approach. Each sub-action gets its own audio file.
    scene.actions = splitLongSpeechActions(
      filterUnspeakableSpeechActions(scene.actions),
      providerId,
    );

    // Use scene order to make audio IDs unique across scenes
    const sceneOrder = scene.order;

    for (const action of scene.actions) {
      if (action.type !== 'speech' || !(action as SpeechAction).text) {
        skipped += 1;
        continue;
      }
      const speechAction = action as ServerTransportSpeechAction;
      // Server transport emits the derived id plus the serving URL; the
      // client-side converter collapses the pair into one pool asset on
      // first load. Browser generation allocates pool ids directly.
      const audioId = `tts_s${sceneOrder}_${action.id}`;

      try {
        const result = await generateTTS(
          {
            providerId,
            modelId: byokModel || DEFAULT_TTS_MODELS[providerId as keyof typeof DEFAULT_TTS_MODELS] || '',
            apiKey,
            baseUrl: ttsBaseUrl,
            voice,
            speed: speechAction.speed,
          },
          speechAction.text,
        );

        const outputFormat = result.format || format;
        const audio = outputFormat === 'wav' ? finalizeWav(Buffer.from(result.audio)) : result.audio;
        const filename = `${audioId}.${outputFormat}`;
        await fs.writeFile(path.join(audioDir, filename), audio);

        speechAction.audioId = audioId;
        const version = createHash('sha256').update(audio).digest('hex').slice(0, 12);
        speechAction.audioUrl = `${mediaServingUrl(baseUrl, classroomId, `audio/${filename}`)}?v=${version}`;
        delete (speechAction as ServerTransportSpeechAction & { audioInvalidated?: boolean })
          .audioInvalidated;
        generated += 1;
        log.info(`Generated TTS: ${filename} (${result.audio.length} bytes)`);
      } catch (err) {
        failed += 1;
        log.warn(`TTS generation failed for action ${action.id}:`, err);
      }
    }
  }

  return { generated, failed, skipped };
}
