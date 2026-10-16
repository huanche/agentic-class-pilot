import { afterEach, describe, expect, it, vi } from 'vitest';
import { generateTTS } from '@/lib/audio/tts-providers';

describe('Qwen synthesis language follows known course language', () => {
  afterEach(() => vi.unstubAllGlobals());
  it.each([
    ['zh-CN', '中位数先排序：1、2、3、4、20。', 'Chinese'],
    ['使用简体中文讲解，保留技术名称。', '中位数先排序：1、2、3、4、20。', 'Chinese'],
    ['zh-CN', 'Python 的 NameError 表示名称未定义。', 'Auto'],
    ['zh-CN', 'int i = 2.56，转换后为 2。', 'Auto'],
    ['ja-JP', '注意事項', 'Japanese'],
    ['ja-JP', '中央値を求めます。', 'Japanese'],
    ['en-US', 'The median is three.', 'English'],
    [undefined, '中位数先排序：1、2、3、4、20。', 'Auto'],
    ['zh-CN', 'こんにちは。', 'Auto'],
  ])('sends %s / %s as %s', async (languageType, text, expected) => {
    const fetchMock = vi.fn(async (input: string | URL | Request) =>
      String(input).includes('/generation')
        ? new Response(
            JSON.stringify({ output: { audio: { url: 'https://audio.example.test/voice.wav' } } }),
            { headers: { 'content-type': 'application/json' } },
          )
        : new Response(new Uint8Array(44)),
    );
    vi.stubGlobal('fetch', fetchMock);
    await generateTTS(
      {
        providerId: 'qwen-tts',
        apiKey: 'test-key',
        voice: 'Cherry',
        providerOptions: { languageType },
      },
      text,
    );
    const request = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(String(request[1].body)).input).toMatchObject({
      text,
      language_type: expected,
    });
  });
});
