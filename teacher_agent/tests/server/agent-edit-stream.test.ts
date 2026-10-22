import { afterEach, describe, expect, it, vi } from 'vitest';
import type { AgentEvent } from '@earendil-works/pi-agent-core';
import { createAgentEditResponse } from '@/lib/server/agent-edit-stream';

function pendingAgent() {
  let resolve!: () => void;
  const pending = new Promise<void>((done) => {
    resolve = done;
  });
  let send = (_event: AgentEvent) => {};
  const unsubscribe = vi.fn();
  const agent = {
    prompt: vi.fn(() => pending),
    waitForIdle: vi.fn(async () => {}),
    subscribe: vi.fn((listener: typeof send) => {
      send = listener;
      return unsubscribe;
    }),
    abort: vi.fn(),
  };
  return { agent, resolve, send: (event: AgentEvent) => send(event), unsubscribe };
}
const decode = (value: Uint8Array | undefined) => new TextDecoder().decode(value);
afterEach(() => vi.useRealTimers());

describe('editor SSE lifecycle', () => {
  it('flushes immediately and keeps an 80-second quiet tool call alive every 10 seconds', async () => {
    vi.useFakeTimers();
    const mock = pendingAgent();
    const response = createAgentEditResponse({
      agent: mock.agent,
      message: '内容丰富点',
      signal: new AbortController().signal,
      onAbort: vi.fn(),
      onError: vi.fn(),
    });
    expect(response.headers.get('cache-control')).toContain('no-transform');
    expect(response.headers.get('x-accel-buffering')).toBe('no');
    const reader = response.body!.getReader();
    expect(decode((await reader.read()).value)).toContain(': connected');
    for (let tick = 0; tick < 8; tick++) {
      await vi.advanceTimersByTimeAsync(10_000);
      expect(decode((await reader.read()).value)).toBe(':heartbeat\n\n');
    }
    mock.send({ type: 'agent_end', messages: [] });
    expect(decode((await reader.read()).value)).toContain('agent_end');
    mock.resolve();
    expect(decode((await reader.read()).value)).toContain('event: close');
    expect((await reader.read()).done).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
    expect(mock.unsubscribe).toHaveBeenCalledOnce();
  });
  it.each(['request', 'reader'] as const)(
    'aborts work and clears heartbeat on %s cancellation',
    async (source) => {
      vi.useFakeTimers();
      const mock = pendingAgent();
      const abort = new AbortController();
      const onAbort = vi.fn();
      const onError = vi.fn();
      const response = createAgentEditResponse({
        agent: mock.agent,
        message: '内容丰富点',
        signal: abort.signal,
        onAbort,
        onError,
      });
      const reader = response.body!.getReader();
      await reader.read();
      if (source === 'request') abort.abort();
      else await reader.cancel();
      mock.resolve();
      await vi.advanceTimersByTimeAsync(20_000);
      expect(mock.agent.abort).toHaveBeenCalledOnce();
      expect(onAbort).toHaveBeenCalledOnce();
      expect(onError).not.toHaveBeenCalled();
      expect(mock.unsubscribe).toHaveBeenCalledOnce();
      expect(vi.getTimerCount()).toBe(0);
      expect((await reader.read()).done).toBe(true);
    },
  );
  it('reports a server exception as a readable event before closing the stream', async () => {
    const mock = pendingAgent();
    mock.agent.prompt.mockRejectedValueOnce(new Error('provider failed'));
    const onError = vi.fn();
    const response = createAgentEditResponse({
      agent: mock.agent,
      message: '内容丰富点',
      signal: new AbortController().signal,
      onAbort: vi.fn(),
      onError,
    });
    const text = await response.text();
    expect(text).toContain('transport_error');
    expect(text).toContain('页面修改过程中发生错误');
    expect(text).toContain('event: close');
    expect(onError).toHaveBeenCalledOnce();
    expect(mock.unsubscribe).toHaveBeenCalledOnce();
  });
});
