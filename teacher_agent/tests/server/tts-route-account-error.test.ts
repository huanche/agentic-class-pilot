import { beforeEach, describe, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({ generate: vi.fn() }));
vi.mock('@/lib/audio/tts-providers', () => ({
  generateTTS: mocks.generate,
  TTSRateLimitError: class extends Error {},
}));
vi.mock('@/lib/server/usage-storage', () => ({ recordGenerationUsage: vi.fn() }));
vi.mock('@/lib/server/provider-config', () => ({
  isServerConfiguredProvider: () => true,
  isServerTTSProviderDisabled: () => false,
  resolveTTSApiKey: () => 'test-key',
  resolveTTSBaseUrl: () => undefined,
  resolveTTSModel: () => undefined,
}));
import { POST } from '@/app/api/generate/tts/route';
describe('TTS account error response', () => {
  beforeEach(() => {
    mocks.generate.mockReset();
  });
  it.each([402, 403])(
    'preserves permanent status %s instead of retryable 500',
    async (statusCode) => {
      mocks.generate.mockRejectedValue(
        Object.assign(new Error('配音服务账户不可用，请检查服务配置。'), {
          errorCode: 'TTS_PROVIDER_ACCOUNT_UNAVAILABLE',
          statusCode,
          isRetryable: false,
        }),
      );
      const response = await POST(
        new Request('https://teacher.example/api/generate/tts', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            text: '同学们好',
            audioId: 'tts_s1_intro',
            ttsProviderId: 'qwen-tts',
            ttsVoice: 'Cherry',
          }),
        }) as never,
      );
      expect(response.status).toBe(statusCode);
      expect(await response.json()).toMatchObject({
        success: false,
        errorCode: 'TTS_PROVIDER_ACCOUNT_UNAVAILABLE',
      });
    },
  );
});
