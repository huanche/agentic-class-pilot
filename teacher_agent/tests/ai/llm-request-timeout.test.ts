import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const aiMock = vi.hoisted(() => ({
  generateText: vi.fn(
    async (
      params: unknown,
    ): Promise<{ text: string; params: unknown; usage?: unknown; totalUsage?: unknown }> => ({
      text: 'ok',
      params,
    }),
  ),
  streamText: vi.fn(),
}));

const usageMock = vi.hoisted(() => ({
  normalizeUsage: vi.fn((usage: unknown) => usage),
  recordUsage: vi.fn(async () => undefined),
}));

vi.mock('ai', () => ({
  generateText: aiMock.generateText,
  streamText: aiMock.streamText,
}));

vi.mock('@/lib/usage/normalize', () => ({
  normalizeUsage: usageMock.normalizeUsage,
}));

vi.mock('@/lib/server/usage-storage', () => ({
  recordUsage: usageMock.recordUsage,
}));

import { callLLM } from '@/lib/ai/llm';

const baseParams = {
  model: { provider: 'openai.responses', modelId: 'gpt-5.6' },
  prompt: 'hi',
} as Parameters<typeof callLLM>[0];

describe('LLM request timeout', () => {
  beforeEach(() => {
    aiMock.generateText.mockClear();
    aiMock.generateText.mockImplementation(async (params: unknown) => ({ text: 'ok', params }));
    delete process.env.LLM_TIMEOUT_MS;
  });

  afterEach(() => {
    delete process.env.LLM_TIMEOUT_MS;
  });

  it('attaches a fresh abort signal per attempt by default', async () => {
    await callLLM(baseParams, 'test');
    expect(aiMock.generateText).toHaveBeenCalledTimes(1);
    expect(aiMock.generateText.mock.calls[0]?.[0]).toEqual(
      expect.objectContaining({ abortSignal: expect.any(AbortSignal) }),
    );

    const firstSignal = (aiMock.generateText.mock.calls[0]?.[0] as { abortSignal: AbortSignal })
      .abortSignal;
    await callLLM(baseParams, 'test');
    const secondSignal = (aiMock.generateText.mock.calls[1]?.[0] as { abortSignal: AbortSignal })
      .abortSignal;
    expect(secondSignal).not.toBe(firstSignal);
  });

  it('omits the signal entirely when LLM_TIMEOUT_MS=0', async () => {
    process.env.LLM_TIMEOUT_MS = '0';
    await callLLM(baseParams, 'test');
    expect(aiMock.generateText.mock.calls[0]?.[0]).not.toHaveProperty('abortSignal');
  });

  it('honours LLM_TIMEOUT_MS for the window length', async () => {
    process.env.LLM_TIMEOUT_MS = '2500';
    await callLLM(baseParams, 'test');
    const signal = (aiMock.generateText.mock.calls[0]?.[0] as { abortSignal: AbortSignal })
      .abortSignal;
    // Not aborted immediately — the cap is 2.5s away, not 10 minutes.
    expect(signal.aborted).toBe(false);
    await new Promise((resolve) => setTimeout(resolve, 2600));
    expect(signal.aborted).toBe(true);
  });

  it('surfaces an abort as an explicit timeout error', async () => {
    aiMock.generateText.mockImplementationOnce(
      () =>
        Promise.reject(
          Object.assign(new Error('This operation was aborted'), { name: 'AbortError' }),
        ) as never,
    );

    await expect(callLLM(baseParams, 'scene-content')).rejects.toThrow(
      /LLM request timed out after \d+ms \[scene-content\]/,
    );
  });

  it('wraps abort errors buried in a cause chain', async () => {
    aiMock.generateText.mockImplementationOnce(
      () =>
        Promise.reject(
          new Error('Request failed', {
            cause: Object.assign(new Error('Signal timed out'), { name: 'TimeoutError' }),
          }),
        ) as never,
    );

    await expect(callLLM(baseParams, 'test')).rejects.toThrow(/LLM request timed out/);
  });

  it('leaves non-abort failures untouched', async () => {
    aiMock.generateText.mockImplementationOnce(
      () => Promise.reject(new Error('Insufficient Balance')) as never,
    );

    await expect(callLLM(baseParams, 'test')).rejects.toThrow('Insufficient Balance');
  });
});
