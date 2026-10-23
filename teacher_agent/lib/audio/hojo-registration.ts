import type { VoiceRegistrationAdapter } from './voice-registration';

const auth = (key?: string): Record<string, string> =>
  key ? { Authorization: `Bearer ${key}` } : {};
export const hojoVoiceRegistrationAdapter: VoiceRegistrationAdapter = {
  supportsRegistration: () => true,
  async voiceExists(config, voiceId) {
    const response = await fetch(
      `${config.baseUrl.replace(/\/$/, '')}/audio/voices/${encodeURIComponent(voiceId)}`,
      {
        headers: auth(config.apiKey),
        signal: AbortSignal.timeout(15_000),
      },
    );
    if (response.status === 404) return false;
    if (!response.ok) throw new Error(`无法检查 Hojo 克隆音色（${response.status}）`);
    return true;
  },
  async registerVoice(config, params) {
    const response = await fetch(`${config.baseUrl.replace(/\/$/, '')}/audio/voices`, {
      method: 'POST',
      signal: AbortSignal.timeout(30_000),
      headers: { 'Content-Type': 'application/json', ...auth(config.apiKey) },
      body: JSON.stringify({
        voice_id: params.voiceId,
        reference_audio: params.referenceAudioBase64,
        reference_text: params.referenceText || '',
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Hojo 克隆音色保存失败');
    return params.voiceId;
  },
  async bootstrapReferenceClip() {
    throw new Error('Hojo 80M 克隆需要上传参考音频');
  },
};
