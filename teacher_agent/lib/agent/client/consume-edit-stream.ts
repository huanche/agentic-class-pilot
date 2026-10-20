import type { AgentEvent } from '@earendil-works/pi-agent-core';

export const EDIT_CONNECTION_INTERRUPTED = '与服务器的连接中断，请重试本页修改。';

/** Heartbeats carry no data; an EOF without agent_end is not a successful edit. */
export async function consumeEditStream(
  response: Response,
  onEvent: (event: AgentEvent) => Promise<void>,
) {
  if (!response.body) throw new Error(EDIT_CONNECTION_INTERRUPTED);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let ended = false;
  try {
    for (;;) {
      const { value, done } = await reader.read().catch(() => {
        throw new Error(EDIT_CONNECTION_INTERRUPTED);
      });
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const chunks = buffer.split('\n\n');
      buffer = chunks.pop() ?? '';
      for (const chunk of chunks) {
        const line = chunk.split('\n').find((part) => part.startsWith('data:'));
        if (!line) continue;
        const json = line.slice(5).trim();
        if (!json || json === '{}') continue;
        let event: AgentEvent | { type: 'transport_error'; message: string };
        try {
          event = JSON.parse(json);
        } catch {
          continue;
        }
        if (event.type === 'transport_error') throw new Error(event.message);
        if (event.type === 'agent_end') ended = true;
        await onEvent(event);
      }
    }
    if (!ended) throw new Error(EDIT_CONNECTION_INTERRUPTED);
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
