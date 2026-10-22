import type { Agent } from '@earendil-works/pi-agent-core';

/** Keep long content/action generation alive even when the model emits no deltas. */
export function createAgentEditResponse({
  agent,
  message,
  signal,
  onAbort,
  onError,
}: {
  agent: Pick<Agent, 'prompt' | 'waitForIdle' | 'subscribe' | 'abort'>;
  message: string;
  signal: AbortSignal;
  onAbort: () => void;
  onError: (error: unknown) => void;
}) {
  const encoder = new TextEncoder();
  let cancel = () => {};
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      let closed = false;
      let heartbeat: ReturnType<typeof setInterval> | undefined;
      let unsubscribe = () => {};
      const cleanup = () => {
        clearInterval(heartbeat);
        heartbeat = undefined;
        unsubscribe();
        signal.removeEventListener('abort', abort);
      };
      const write = (frame: string) => {
        if (closed) return;
        try {
          controller.enqueue(encoder.encode(frame));
        } catch {
          abort();
        }
      };
      const close = () => {
        if (closed) return;
        closed = true;
        cleanup();
        try {
          controller.close();
        } catch {
          /* consumer already cancelled */
        }
      };
      const abort = () => {
        if (closed) return;
        close();
        agent.abort();
        onAbort();
      };
      cancel = abort;
      if (signal.aborted) {
        abort();
        return;
      }
      signal.addEventListener('abort', abort, { once: true });
      unsubscribe = agent.subscribe((event) => write(`data: ${JSON.stringify(event)}\n\n`));
      // Flush headers immediately; comments are ignored by the event consumer.
      write(': connected\n\n');
      heartbeat = setInterval(() => write(':heartbeat\n\n'), 10_000);

      // Do not make ReadableStream.start wait for the complete model/tool turn.
      void (async () => {
        try {
          await agent.prompt(message);
          await agent.waitForIdle();
        } catch (error) {
          if (!closed) {
            onError(error);
            write(
              `data: ${JSON.stringify({ type: 'transport_error', message: '页面修改过程中发生错误，请稍后重试。' })}\n\n`,
            );
          }
        } finally {
          write('event: close\ndata: {}\n\n');
          close();
        }
      })();
    },
    cancel() {
      cancel();
    },
  });
  return new Response(stream, {
    headers: {
      'Content-Type': 'text/event-stream; charset=utf-8',
      'Cache-Control': 'no-cache, no-transform',
      'X-Accel-Buffering': 'no',
      Connection: 'keep-alive',
    },
  });
}
