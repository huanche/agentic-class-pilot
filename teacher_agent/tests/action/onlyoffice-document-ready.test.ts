import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import { afterEach, describe, expect, it, vi } from 'vitest';

afterEach(() => vi.useRealTimers());
async function boot() {
  vi.useFakeTimers();
  const code = await readFile('services/onlyoffice/public/frame.js', 'utf8');
  let listener!: (event: unknown) => void;
  let events!: { onDocumentReady: () => void; onError: (event: unknown) => void };
  const parent = { postMessage: vi.fn() },
    commands: string[] = [],
    status = { hidden: false, textContent: '' };
  const origin = 'https://classroom.example',
    nonce = 'test-nonce';
  const emit = (event: string, id?: number) =>
    listener({
      origin,
      source: peer,
      data: { channel: 'agentic-onlyoffice-bridge-v1', nonce, event, id },
    });
  const peer = {
    postMessage: (data: { command: string; id: number }) => {
      commands.push(data.command);
      queueMicrotask(() => {
        emit('ack', data.id);
        if (data.command === 'start') emit('onSlideShowBegin');
      });
    },
  };
  const context = {
    URLSearchParams,
    Promise,
    Map,
    Object,
    Number,
    Math,
    Error,
    setTimeout,
    clearTimeout,
    performance,
    queueMicrotask,
    location: { origin, search: '?classroom=c&scene=s' },
    parent,
    addEventListener: (_type: string, fn: typeof listener) => {
      listener = fn;
    },
    document: {
      getElementById: () => status,
      createElement: () => ({}),
      head: { append: (s: { onload: () => void }) => s.onload() },
    },
    fetch: async () => ({
      ok: true,
      json: async () => ({ nonce, page: 1, steps: [], editor: {}, engineUrl: '/engine.js' }),
    }),
    DocsAPI: {
      DocEditor: function (_id: string, config: { events: typeof events }) {
        events = config.events;
      },
    },
  };
  await vm.runInNewContext(`(async()=>{${code}\n})()`, context);
  return { events, parent, commands, status, pluginReady: () => emit('ready') };
}
describe('ONLYOFFICE document and plugin readiness', () => {
  it('keeps loading when the plugin starts before the document is loaded', async () => {
    const app = await boot();
    app.pluginReady();
    await vi.advanceTimersByTimeAsync(2000);
    expect(app.commands).toEqual([]);
    expect(app.status.hidden).toBe(false);
    app.events.onDocumentReady();
    await vi.advanceTimersByTimeAsync(1500);
    expect(app.commands).toEqual(['start', 'goto']);
    expect(app.status.hidden).toBe(true);
    expect(app.parent.postMessage).toHaveBeenCalledWith(
      expect.objectContaining({ event: 'ready' }),
      'https://classroom.example',
    );
  });
  it('also waits for the control plugin if the document is ready first; duplicate events do not restart playback', async () => {
    const app = await boot();
    app.events.onDocumentReady();
    expect(app.commands).toEqual([]);
    app.pluginReady();
    await vi.advanceTimersByTimeAsync(1500);
    app.pluginReady();
    app.events.onDocumentReady();
    await vi.advanceTimersByTimeAsync(1500);
    expect(app.commands).toEqual(['start', 'goto']);
  });
});
