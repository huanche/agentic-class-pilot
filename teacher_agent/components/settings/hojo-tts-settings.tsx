'use client';

import { useState } from 'react';
import { Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useSettingsStore } from '@/lib/store/settings';
import {
  HOJO_40M_MODEL,
  HOJO_80M_MODEL,
  HOJO_CLONE_PREFIX,
  HOJO_DEFAULT_VOICE,
  HOJO_REFERENCE_VOICE,
  HOJO_VOICES,
} from '@/lib/audio/hojo';
import { normalizeVoxCPMReferenceAudio } from '@/lib/audio/voxcpm-voices';

export function HojoTTSSettings({ enabled }: { enabled: boolean }) {
  const config = useSettingsStore((state) => state.ttsProvidersConfig['hojo-tts']);
  const activeProvider = useSettingsStore((state) => state.ttsProviderId);
  const activeVoice = useSettingsStore((state) => state.ttsVoice);
  const model = config?.modelId || HOJO_40M_MODEL;
  const [file, setFile] = useState<File>();
  const [name, setName] = useState('');
  const [referenceText, setReferenceText] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const clones = (config?.customVoices ?? []).filter((voice) =>
    /^hojo_clone_[a-f0-9]{32}$/.test(voice.id),
  );
  const voices = [
    ...HOJO_VOICES.filter((voice) => voice.compatibleModels?.includes(model)),
    ...(model === HOJO_80M_MODEL ? clones : []),
  ];
  const selectedVoice =
    activeProvider === 'hojo-tts' && voices.some((voice) => voice.id === activeVoice)
      ? activeVoice
      : voices[0]?.id;
  const select = (modelId: string, voice: string) => {
    const store = useSettingsStore.getState();
    store.setTTSProvider('hojo-tts');
    store.setTTSProviderConfig('hojo-tts', { modelId });
    store.setTTSVoice(voice);
  };
  const saveClone = async () => {
    if (!file || !name.trim() || saving) return;
    setSaving(true);
    setError('');
    try {
      const normalized = await normalizeVoxCPMReferenceAudio(file, file.name);
      const base64 = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onerror = () => reject(new Error('读取参考音频失败'));
        reader.onload = () => resolve(String(reader.result).split(',')[1]);
        reader.readAsDataURL(normalized.blob);
      });
      const voiceId = `${HOJO_CLONE_PREFIX}${crypto.randomUUID().replaceAll('-', '')}`;
      const response = await fetch('/api/generate/voice', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          providerId: 'hojo-tts',
          voiceId,
          referenceAudioBase64: base64,
          referenceText,
          mimeType: 'audio/wav',
          ttsBaseUrl: config?.baseUrl,
          ttsApiKey: config?.apiKey,
          ttsModelId: HOJO_80M_MODEL,
        }),
      });
      const data = await response.json();
      if (!response.ok || data.success === false) throw new Error(data.error || '保存克隆音色失败');
      const store = useSettingsStore.getState();
      const current = store.ttsProvidersConfig['hojo-tts']?.customVoices ?? [];
      store.setTTSProviderConfig('hojo-tts', {
        customVoices: [...current, { id: voiceId, name: name.trim() }],
      });
      select(HOJO_80M_MODEL, voiceId);
      setFile(undefined);
      setName('');
      setReferenceText('');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setSaving(false);
    }
  };
  return (
    <div className="space-y-4 rounded-xl border border-border/60 p-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="space-y-2 text-sm font-medium">
          Hojo 模型
          <select
            aria-label="Hojo 模型"
            value={model}
            disabled={!enabled || saving}
            onChange={(event) =>
              select(
                event.target.value,
                event.target.value === HOJO_40M_MODEL ? HOJO_DEFAULT_VOICE : HOJO_REFERENCE_VOICE,
              )
            }
            className="block w-full rounded-md border bg-background px-3 py-2 text-sm font-normal"
          >
            <option value={HOJO_40M_MODEL}>Hojo-TTS-Light-40M · 固定音色</option>
            <option value={HOJO_80M_MODEL}>Hojo-TTS-Light-80M · 声音克隆</option>
          </select>
        </label>
        <label className="space-y-2 text-sm font-medium">
          Hojo 音色
          <select
            aria-label="Hojo 音色"
            value={selectedVoice}
            disabled={!enabled || saving}
            onChange={(event) => select(model, event.target.value)}
            className="block w-full rounded-md border bg-background px-3 py-2 text-sm font-normal"
          >
            {voices.map((voice) => (
              <option key={voice.id} value={voice.id}>
                {voice.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      <p className="text-xs leading-5 text-muted-foreground">
        40M 提供中英文固定音色；80M 支持参考音频克隆。首次使用会加载模型，实际速度取决于 CPU
        和讲稿长度。
      </p>
      {model === HOJO_80M_MODEL && (
        <fieldset disabled={!enabled || saving} className="space-y-3 border-t pt-4">
          <legend className="text-sm font-medium">添加克隆音色</legend>
          <Input
            aria-label="克隆音色名称"
            placeholder="音色名称"
            value={name}
            maxLength={60}
            onChange={(event) => setName(event.target.value)}
          />
          <Label className="block text-xs">
            参考音频（1～30 秒）
            <input
              aria-label="Hojo 参考音频"
              type="file"
              accept="audio/*"
              className="mt-2 block w-full text-sm"
              onChange={(event) => setFile(event.target.files?.[0])}
            />
          </Label>
          <Input
            aria-label="参考音频文字"
            placeholder="参考音频中说的话（选填，有助于对齐）"
            value={referenceText}
            maxLength={2000}
            onChange={(event) => setReferenceText(event.target.value)}
          />
          <p className="text-xs text-muted-foreground">
            参考音频保存在当前配置的 Hojo 服务中；更换服务后需要重新添加。
          </p>
          <Button
            type="button"
            variant="outline"
            disabled={!enabled || !file || !name.trim() || saving}
            onClick={() => void saveClone()}
          >
            {saving && <Loader2 className="mr-2 size-4 animate-spin" />}{' '}
            {saving ? '保存中…' : '保存并使用此音色'}
          </Button>
        </fieldset>
      )}
      {error && (
        <p role="alert" className="text-sm text-red-600">
          {error}
        </p>
      )}
    </div>
  );
}
