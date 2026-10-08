import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { requestTeacherAgentTurn } from '@/lib/course-space/teacher-agent-request';

const input = {
  courseId: 'course-a',
  modelConfig: { modelString: 'openai:model', apiKey: 'mock-model-key', baseUrl: 'https://model.example/v1', providerType: 'openai', thinkingConfig: { enabled: true } },
  body: { sessionId: 's1', message: '解释知识点', history: [], attachments: [], scope: { type: 'course' as const }, deepInteraction: true },
};
const fetchMock = vi.fn<typeof fetch>();
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'content-type': 'application/json' } });

describe('teacher UI request chain', () => {
  beforeEach(() => { fetchMock.mockReset(); vi.stubGlobal('fetch', fetchMock); });
  afterEach(() => vi.unstubAllGlobals());

  it('forwards model, thinking, scope, history and screenshot without searching by default', async () => {
    const response = json({ success: true });
    fetchMock.mockResolvedValue(response);
    const body = { ...input.body, attachments: [{ name: 'shot.png', mimeType: 'image/png', dataUrl: 'data:image/png;base64,YQ==' }] };
    expect(await requestTeacherAgentTurn({ ...input, body })).toBe(response);
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock.mock.calls[0][0]).toBe('/api/course-space/course-a/agent');
    expect(fetchMock.mock.calls[0][1]?.headers).toMatchObject({ 'x-model': 'openai:model', 'x-api-key': 'mock-model-key', 'x-base-url': 'https://model.example/v1', 'x-provider-type': 'openai' });
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({ ...body, thinkingConfig: input.modelConfig.thinkingConfig });
  });

  it('awaits search before chat and keeps search credentials out of the agent body', async () => {
    fetchMock.mockResolvedValueOnce(json({ success: true, data: { context: '来源 https://source.example' } })).mockResolvedValueOnce(json({ success: true }));
    await requestTeacherAgentTurn({ ...input, webSearch: { providerId: 'tavily', providerConfig: { apiKey: 'mock-search-key' } } });
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual(['/api/web-search', '/api/course-space/course-a/agent']);
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toMatchObject({ query: input.body.message, providerId: 'tavily', apiKey: 'mock-search-key', thinkingConfig: input.modelConfig.thinkingConfig });
    const turn = JSON.parse(String(fetchMock.mock.calls[1][1]?.body));
    expect(turn.webContext).toBe('来源 https://source.example');
    expect(turn.apiKey).toBeUndefined();
  });

  it.each([json({ success: false, error: { message: '检索失败' } }), json({ error: '检索失败' }, 503)])('does not call the agent when search fails', async (response) => {
    fetchMock.mockResolvedValueOnce(response);
    await expect(requestTeacherAgentTurn({ ...input, webSearch: { providerId: 'tavily' } })).rejects.toThrow('检索失败');
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it('bounds legacy search context and ignores non-string context', async () => {
    fetchMock.mockResolvedValueOnce(json({ context: 'W'.repeat(24000) + 'TRUNCATED' })).mockResolvedValueOnce(json({ success: true }));
    await requestTeacherAgentTurn({ ...input, webSearch: { providerId: 'tavily' } });
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body)).webContext).toBe('W'.repeat(24000));
    fetchMock.mockReset();
    fetchMock.mockResolvedValueOnce(json({ data: { context: { unsafe: true } } })).mockResolvedValueOnce(json({ success: true }));
    await requestTeacherAgentTurn({ ...input, webSearch: { providerId: 'tavily' } });
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body)).webContext).toBeUndefined();
  });
});