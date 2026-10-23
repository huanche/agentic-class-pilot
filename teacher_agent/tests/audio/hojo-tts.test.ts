import { afterEach, expect, it, vi } from 'vitest';
import { generateTTS } from '@/lib/audio/tts-providers';
import { getEnabledProvidersWithVoices, resolveAgentVoice } from '@/lib/audio/voice-resolver';
import { HOJO_40M_MODEL, HOJO_80M_MODEL } from '@/lib/audio/hojo';

afterEach(() => vi.unstubAllGlobals());

it('keeps 40M preset voices and 80M cloned voices in their compatible model groups', () => {
  const provider = getEnabledProvidersWithVoices({
    'hojo-tts': {
      isServerConfigured: true,
      customVoices: [{ id: 'hojo_clone_' + 'a'.repeat(32), name: '测试参考音色' }],
    },
  })[0];
  const small = provider.modelGroups.find((group) => group.modelId === HOJO_40M_MODEL)!;
  const large = provider.modelGroups.find((group) => group.modelId === HOJO_80M_MODEL)!;
  expect(small.voices).toHaveLength(15);
  expect(small.voices.every((voice) => !voice.id.startsWith('hojo_clone_'))).toBe(true);
  expect(large.voices.some((voice) => voice.id.startsWith('hojo_clone_'))).toBe(true);
  expect(provider.voices).toHaveLength(15);
  expect(provider.voices.some((voice) => voice.id.startsWith('hojo_clone_'))).toBe(false);
});

it('automatically assigns only voices compatible with the selected 80M model', () => {
  const providers = getEnabledProvidersWithVoices({
    'hojo-tts': { isServerConfigured: true, modelId: HOJO_80M_MODEL },
  });
  const resolved = resolveAgentVoice(
    { id: 'teacher', name: 'Teacher', role: 'teacher' } as Parameters<typeof resolveAgentVoice>[0],
    0,
    providers,
  );
  expect(resolved).toMatchObject({ modelId: HOJO_80M_MODEL, voiceId: 'hojo_80m_zh1' });
});

it('sends the chosen local model/voice and rejects successful HTTP responses containing non-audio', async () => {
  const request = vi.fn(async () => new Response('not audio', { status: 200 }));
  vi.stubGlobal('fetch', request);
  await expect(
    generateTTS(
      {
        providerId: 'hojo-tts',
        modelId: HOJO_80M_MODEL,
        voice: 'hojo_80m_zh1',
        baseUrl: 'http://127.0.0.1:13306/v1/',
      },
      '循环先判断条件。',
    ),
  ).rejects.toThrow('有效 WAV');
  const [url, init] = request.mock.calls[0] as unknown as [string, RequestInit];
  expect(url).toBe('http://127.0.0.1:13306/v1/audio/speech');
  expect(JSON.parse(init.body as string)).toMatchObject({
    model: HOJO_80M_MODEL,
    voice: 'hojo_80m_zh1',
    speed: 1,
  });
});
