import { afterEach, describe, expect, it, vi } from 'vitest';
import { generateTTS } from '@/lib/audio/tts-providers';

describe('Qwen account failures are permanent generation errors', () => {
  afterEach(() => vi.unstubAllGlobals());
  it.each([
    ['Arrearage', 400, 402],
    ['Arrearage', 200, 402],
    ['InvalidApiKey', 401, 403],
  ])(
    'classifies %s without leaking raw provider details',
    async (code, upstreamStatus, statusCode) => {
      const fetchMock = vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            code,
            message: 'private-provider-detail',
            request_id: 'request-secret',
          }),
          { status: upstreamStatus },
        ),
      );
      vi.stubGlobal('fetch', fetchMock);
      const error = await generateTTS(
        { providerId: 'qwen-tts', apiKey: 'test-key', voice: 'Cherry' },
        '同学们好',
      ).catch((error) => error);
      expect(error).toMatchObject({
        errorCode: 'TTS_PROVIDER_ACCOUNT_UNAVAILABLE',
        statusCode,
        isRetryable: false,
      });
      expect(error.message).not.toContain('private-provider-detail');
      expect(error.message).not.toContain('request-secret');
      expect(fetchMock).toHaveBeenCalledTimes(1);
    },
  );
  it('does not turn a temporary upstream error into an account failure', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response('upstream busy', { status: 503 })),
    );
    const error = await generateTTS(
      { providerId: 'qwen-tts', apiKey: 'test-key', voice: 'Cherry' },
      '同学们好',
    ).catch((error) => error);
    expect(error.errorCode).not.toBe('TTS_PROVIDER_ACCOUNT_UNAVAILABLE');
  });
});
