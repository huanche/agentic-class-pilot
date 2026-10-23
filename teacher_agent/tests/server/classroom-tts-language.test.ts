import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Scene } from '@/lib/types/stage';
const mocks = vi.hoisted(() => ({
  tts: vi.fn(async () => ({ audio: new Uint8Array(44), format: 'wav' })),
  write: vi.fn(async () => {}),
  providers: vi.fn((): Record<string, { disabled?: boolean }> => ({ 'qwen-tts': {} })),
  disabled: vi.fn((_provider: string) => false),
}));
vi.mock('fs', () => ({ promises: { mkdir: vi.fn(async () => {}), writeFile: mocks.write } }));
vi.mock('@/lib/audio/tts-providers', () => ({ generateTTS: mocks.tts }));
vi.mock('@/lib/server/provider-config', () => ({
  getServerTTSProviders: mocks.providers,
  isServerTTSProviderDisabled: mocks.disabled,
  resolveTTSApiKey: () => 'test',
  resolveTTSBaseUrl: () => undefined,
  resolveTTSVoice: (_provider: string, voice?: string) => voice,
  resolveTTSModel: (_provider: string, model?: string) => model,
}));
import { generateTTSForClassroom } from '@/lib/server/classroom-media-generation';

beforeEach(() => {
  mocks.tts.mockReset();
  mocks.tts.mockImplementation(async () => ({ audio: new Uint8Array(44), format: 'wav' }));
  mocks.providers.mockReset();
  mocks.providers.mockReturnValue({ 'qwen-tts': {} });
  mocks.disabled.mockReset();
  mocks.disabled.mockReturnValue(false);
});

function narrationScene() {
  return {
    id: 'voice-scene',
    stageId: 'voice-stage',
    order: 1,
    title: 'Voice',
    type: 'slide',
    content: { type: 'slide', canvas: { elements: [] } },
    actions: [{ id: 'speech', type: 'speech', text: '你好，欢迎来到课堂。' }],
  } as unknown as Scene;
}
describe('server narration language', () => {
  it('preserves the chosen Hojo model and voice for background narration', async () => {
    mocks.providers.mockReturnValue({ 'lemonade-tts': {}, 'hojo-tts': {} });
    await generateTTSForClassroom(
      [narrationScene()],
      'voice-stage',
      'http://localhost',
      undefined,
      {
        voiceSelection: {
          providerId: 'hojo-tts',
          modelId: 'hojo-tts-light-80m',
          voice: 'hojo_80m_zh1',
        },
      },
    );
    expect(mocks.tts).toHaveBeenCalledWith(
      expect.objectContaining({
        providerId: 'hojo-tts',
        modelId: 'hojo-tts-light-80m',
        voice: 'hojo_80m_zh1',
      }),
      expect.any(String),
    );
  });
  it('stops queued clips on failure and waits for in-flight audio before returning to cleanup', async () => {
    let release: () => void = () => {};
    let finished = false;
    const inFlight = new Promise<void>((resolve) => {
      release = resolve;
    });
    mocks.tts
      .mockRejectedValueOnce(new Error('account unavailable'))
      .mockImplementationOnce(async () => {
        await inFlight;
        return { audio: new Uint8Array(44), format: 'wav' };
      });
    const scene = narrationScene();
    scene.actions = [1, 2, 3, 4].map((index) => ({
      id: `f${index}`,
      type: 'speech',
      text: `失败测试${index}`,
    }));
    const work = generateTTSForClassroom([scene], 'failure-test', 'http://localhost', undefined, {
      concurrency: 2,
      failFast: true,
    }).catch((error) => {
      finished = true;
      return error;
    });
    await vi.waitFor(() => expect(mocks.tts).toHaveBeenCalledTimes(2));
    expect(finished).toBe(false);
    release();
    expect(await work).toMatchObject({ message: 'account unavailable' });
    expect(mocks.tts).toHaveBeenCalledTimes(2);
  });
  it('synthesizes independent clips concurrently while retaining playback order', async () => {
    const pending: Array<() => void> = [];
    let active = 0;
    let peak = 0;
    mocks.tts.mockImplementation(async () => {
      active++;
      peak = Math.max(peak, active);
      await new Promise<void>((resolve) => pending.push(resolve));
      active--;
      return { audio: new Uint8Array(44), format: 'wav' };
    });
    const scene = narrationScene();
    scene.actions = [1, 2, 3, 4].map((index) => ({
      id: `speech${index}`,
      type: 'speech',
      text: `测试讲稿${index}`,
    }));
    const work = generateTTSForClassroom([scene], 'parallel-test', 'http://localhost', undefined, {
      concurrency: 2,
    });
    await vi.waitFor(() => expect(pending).toHaveLength(2));
    pending.splice(0).forEach((resolve) => resolve());
    await vi.waitFor(() => expect(pending).toHaveLength(2));
    pending.splice(0).forEach((resolve) => resolve());
    await work;
    expect(peak).toBe(2);
    expect(scene.actions.map((action) => action.id)).toEqual([
      'speech1',
      'speech2',
      'speech3',
      'speech4',
    ]);
    mocks.tts.mockImplementation(async () => ({ audio: new Uint8Array(44), format: 'wav' }));
  });
  it('falls back to local TTS when an old per-user cloud config is force-disabled', async () => {
    mocks.providers.mockReturnValue({ 'qwen-tts': { disabled: true }, 'lemonade-tts': {} });
    mocks.disabled.mockImplementation((provider) => provider === 'qwen-tts');
    await generateTTSForClassroom([narrationScene()], 'voice-stage', 'http://localhost', {
      provider: 'qwen-tts',
      apiKey: 'old-user-test-key',
      voice: 'Cherry',
      baseUrl: 'https://old-cloud-provider.example/v1',
    });
    expect(mocks.tts).toHaveBeenCalledWith(
      expect.objectContaining({
        providerId: 'lemonade-tts',
        voice: 'zf_xiaoyi',
        baseUrl: 'http://localhost:13305/v1',
      }),
      expect.any(String),
    );
  });

  it('uses the selected local voice instead of the provider default', async () => {
    mocks.providers.mockReturnValue({ 'lemonade-tts': {} });
    await generateTTSForClassroom(
      [narrationScene()],
      'voice-stage',
      'http://localhost',
      undefined,
      {
        voiceSelection: { providerId: 'lemonade-tts', voice: 'zm_yunxi' },
      },
    );
    expect(mocks.tts).toHaveBeenCalledWith(
      expect.objectContaining({ providerId: 'lemonade-tts', voice: 'zm_yunxi' }),
      '你好，欢迎来到课堂。',
    );
  });

  it('defaults local narration to Xiaoyi when the job has no voice selection', async () => {
    mocks.providers.mockReturnValue({ 'lemonade-tts': {} });
    await generateTTSForClassroom([narrationScene()], 'voice-stage', 'http://localhost');
    expect(mocks.tts).toHaveBeenCalledWith(
      expect.objectContaining({ voice: 'zf_xiaoyi' }),
      expect.any(String),
    );
  });

  it('does not pass a local voice to a different server-selected provider', async () => {
    await generateTTSForClassroom(
      [narrationScene()],
      'voice-stage',
      'http://localhost',
      undefined,
      {
        voiceSelection: { providerId: 'lemonade-tts', voice: 'zf_xiaoyi' },
      },
    );
    expect(mocks.tts).toHaveBeenCalledWith(
      expect.objectContaining({ providerId: 'qwen-tts', voice: 'Cherry' }),
      expect.any(String),
    );
  });

  it('passes course language to TTS without changing the approved text or focus', async () => {
    const scene = {
      id: 's',
      stageId: 'c',
      order: 1,
      title: 'Median',
      type: 'slide',
      content: { type: 'slide', canvas: { elements: [] } },
      actions: [
        { id: 'f', type: 'spotlight', elementId: 'median' },
        { id: 's', type: 'speech', text: '中位数先排序：1、2、3、4、20。' },
      ],
    } as unknown as Scene;
    const result = await generateTTSForClassroom([scene], 'c', 'http://localhost', undefined, {
      isolateAudio: true,
      languageDirective: '使用中文讲解',
    });
    expect(result).toMatchObject({ generated: 1, failed: 0 });
    expect(mocks.tts.mock.calls[0]).toEqual([
      expect.objectContaining({ providerOptions: { languageType: '使用中文讲解' } }),
      '中位数先排序：1、2、3、4、20。',
    ]);
    expect(scene.actions?.[0]).toMatchObject({ type: 'spotlight', elementId: 'median' });
  });
});
