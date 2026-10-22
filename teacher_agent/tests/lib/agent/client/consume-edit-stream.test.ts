import { describe, expect, it, vi } from 'vitest';
import {
  consumeEditStream,
  EDIT_CONNECTION_INTERRUPTED,
} from '@/lib/agent/client/consume-edit-stream';

describe('editor SSE consumer', () => {
  it('ignores heartbeats and handles fragmented events in order', async () => {
    const encoder = new TextEncoder();
    const response = new Response(
      new ReadableStream({
        start(controller) {
          for (const part of [
            ': connected\n\n:heartbeat\n\n',
            'data: {"type":"agent_',
            'start"}\n\n:heartbeat\n\ndata: {"type":"agent_end","messages":[]}\n\n',
            'event: close\ndata: {}\n\n',
          ])
            controller.enqueue(encoder.encode(part));
          controller.close();
        },
      }),
    );
    const handle = vi.fn();
    await consumeEditStream(response, handle);
    expect(handle.mock.calls.map(([event]) => event.type)).toEqual(['agent_start', 'agent_end']);
  });
  it('reports a premature EOF instead of claiming success', async () => {
    await expect(
      consumeEditStream(new Response('data: {"type":"agent_start"}\n\n'), vi.fn()),
    ).rejects.toThrow(EDIT_CONNECTION_INTERRUPTED);
  });
  it('gives a clear connection error when the response reader fails', async () => {
    const response = new Response(
      new ReadableStream({
        start(controller) {
          controller.error(new TypeError('Failed to fetch'));
        },
      }),
    );
    await expect(consumeEditStream(response, vi.fn())).rejects.toThrow(EDIT_CONNECTION_INTERRUPTED);
  });
  it('shows an explicit server error and cancels further consumption', async () => {
    const cancel = vi.fn();
    const response = new Response(
      new ReadableStream({
        start(controller) {
          controller.enqueue(
            new TextEncoder().encode(
              'data: {"type":"transport_error","message":"页面修改失败"}\n\n',
            ),
          );
        },
        cancel,
      }),
    );
    await expect(consumeEditStream(response, vi.fn())).rejects.toThrow('页面修改失败');
    expect(cancel).toHaveBeenCalledOnce();
  });
});
