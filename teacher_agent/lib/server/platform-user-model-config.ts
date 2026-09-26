/**
 * Platform per-user BYOK model config (个人模型配置).
 *
 * The platform stores each user's own provider credentials (encrypted at
 * rest); this module fetches the decrypted view via the service-key
 * authenticated internal API and caches it briefly. Generation paths use it
 * to override server-managed provider resolution — persisting the user's own
 * key is the point of the platform's 个人模型配置.
 *
 * Together with platform-course-bridge.ts / platform-auth.ts this is part of
 * the platform integration surface: when a new upstream teacher-agent
 * revision is merged, re-port by copying the integration modules and
 * re-applying the minimal hooks listed in docs/platform-integration-porting.md.
 */
import { type NextRequest } from 'next/server';

import { createLogger } from '@/lib/logger';

import { isPlatformAuthEnabled } from './platform-course-bridge';

const log = createLogger('PlatformUserModelConfig');

export interface PlatformLlmConfig {
  baseUrl?: string;
  apiKey?: string;
  model?: string;
}

export interface PlatformTtsConfig {
  provider?: string;
  apiKey?: string;
  baseUrl?: string;
  model?: string;
  voice?: string;
}

export interface PlatformUserModelConfig {
  llm?: PlatformLlmConfig;
  tts?: PlatformTtsConfig;
}

interface CacheEntry {
  config: PlatformUserModelConfig | null;
  at: number;
}

// Positive results are cheap to reuse within a generation burst; negatives
// expire quickly so a user who just saved their config is picked up fast.
const POSITIVE_TTL_MS = 60_000;
const NEGATIVE_TTL_MS = 10_000;
const cache = new Map<string, CacheEntry>();

export function platformUserIdFromRequest(req: NextRequest): string | null {
  if (!isPlatformAuthEnabled()) return null;
  return req.headers.get('x-platform-user-id');
}

export async function fetchPlatformUserModelConfig(
  userId: string,
): Promise<PlatformUserModelConfig | null> {
  const hit = cache.get(userId);
  if (hit) {
    const ttl = hit.config ? POSITIVE_TTL_MS : NEGATIVE_TTL_MS;
    if (Date.now() - hit.at < ttl) return hit.config;
  }
  try {
    const response = await fetch(
      `${process.env.PLATFORM_AUTH_URL}/api/v1/internal/user/${encodeURIComponent(userId)}/model-config`,
      {
        headers: { 'X-Teacher-Service-Key': process.env.PLATFORM_SERVICE_KEY || '' },
        cache: 'no-store',
        signal: AbortSignal.timeout(5000),
      },
    );
    const config = response.ok ? ((await response.json()) as PlatformUserModelConfig) : null;
    cache.set(userId, { config, at: Date.now() });
    return config;
  } catch (error) {
    log.warn('Failed to fetch platform model config; falling back to server providers', error);
    cache.set(userId, { config: null, at: Date.now() });
    return null;
  }
}

export async function getPlatformUserModelConfigForRequest(
  req: NextRequest,
): Promise<PlatformUserModelConfig | null> {
  const userId = platformUserIdFromRequest(req);
  if (!userId) return null;
  return fetchPlatformUserModelConfig(userId);
}

/**
 * The resolveModel override shape: the user's OpenAI-compatible endpoint
 * bound to their own key. Requires apiKey + model, otherwise undefined
 * (no override → server-managed resolution as before).
 */
export function llmOverrideFromConfig(
  config: PlatformUserModelConfig | null | undefined,
): { modelString: string; apiKey: string; baseUrl?: string } | undefined {
  const llm = config?.llm;
  if (!llm?.apiKey || !llm.model) return undefined;
  return {
    modelString: `openai/${llm.model}`,
    apiKey: llm.apiKey,
    baseUrl: llm.baseUrl || undefined,
  };
}
