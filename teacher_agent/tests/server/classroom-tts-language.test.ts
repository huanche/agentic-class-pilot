import { describe, expect, it, vi } from 'vitest';
import type { Scene } from '@/lib/types/stage';
const mocks = vi.hoisted(() => ({
  tts: vi.fn(async () => ({ audio: new Uint8Array(44), format: 'wav' })),
  write: vi.fn(async () => {}),
}));
vi.mock('fs', () => ({ promises: { mkdir: vi.fn(async () => {}), writeFile: mocks.write } }));
vi.mock('@/lib/audio/tts-providers', () => ({ generateTTS: mocks.tts }));
vi.mock('@/lib/server/provider-config', () => ({
  getServerTTSProviders: () => ({ 'qwen-tts': { apiKey: 'test' } }),
  resolveTTSApiKey: () => 'test',
  resolveTTSBaseUrl: () => undefined,
}));
import { generateTTSForClassroom } from '@/lib/server/classroom-media-generation';
describe('server narration language', () => {
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
