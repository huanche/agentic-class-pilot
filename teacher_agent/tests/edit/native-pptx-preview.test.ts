// @vitest-environment jsdom
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Scene } from '@/lib/types/stage';

const mocks = vi.hoisted(() => ({ register: vi.fn(() => vi.fn()) }));
vi.mock('@/lib/store/stage', () => ({
  useStageStore: (selector: (state: unknown) => unknown) =>
    selector({
      stage: { id: 'stage', nativePptx: { clicks: { source: new Array(9).fill({}) } } },
    }),
}));
vi.mock('@/lib/onlyoffice/native-player', () => ({
  registerNativeDriver: mocks.register,
}));
import { NativePptxView } from '@/components/stage/native-pptx-view';

let root: Root;
let host: HTMLDivElement;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.clearAllMocks();
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({ ok: true, json: async () => ({ enabled: true }) })),
  );
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});
const scene = { id: 'page5', outlineId: 'source', type: 'slide' } as Scene;
function message(source: Window, data: object) {
  window.dispatchEvent(
    new MessageEvent('message', {
      origin: window.location.origin,
      source,
      data: { channel: 'agentic-native-pptx-v1', sceneId: scene.id, ...data },
    }),
  );
}

describe('source PPTX preview', () => {
  it('previews the completed native source without registering a playback driver or mutating its canvas', async () => {
    await act(async () =>
      root.render(React.createElement(NativePptxView, { scene, preview: true })),
    );
    const peer = host.querySelector('iframe')!.contentWindow!;
    const post = vi.spyOn(peer, 'postMessage').mockImplementation(() => {});
    await act(async () => message(peer, { event: 'ready' }));
    expect(post).toHaveBeenCalledWith(
      expect.objectContaining({ command: 'seek', step: 9 }),
      window.location.origin,
    );
    expect(mocks.register).not.toHaveBeenCalled();
    await act(async () => message(peer, { event: 'ack', id: 1 }));
    expect(host.textContent).toContain('原稿 · ONLYOFFICE');
    expect(host.querySelector('button')).toBeNull();
    expect(host.textContent).not.toContain('兼容');
  });
  it('leaves the playback view at its initial animation state', async () => {
    await act(async () => root.render(React.createElement(NativePptxView, { scene })));
    const peer = host.querySelector('iframe')!.contentWindow!;
    const post = vi.spyOn(peer, 'postMessage').mockImplementation(() => {});
    await act(async () => message(peer, { event: 'ready' }));
    expect(mocks.register).toHaveBeenCalledOnce();
    expect(post).not.toHaveBeenCalled();
    expect(host.textContent).toContain('原稿 · ONLYOFFICE');
  });

  it('retries the source with a new iframe and ignores messages from the failed frame', async () => {
    await act(async () => root.render(React.createElement(NativePptxView, { scene })));
    const oldFrame = host.querySelector('iframe')!;
    const oldPeer = oldFrame.contentWindow!;
    await act(async () => message(oldPeer, { event: 'error', detail: '原稿引擎未响应' }));
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('原稿引擎未响应');
    expect(host.textContent).not.toContain('兼容');
    expect(host.querySelector('button')?.textContent).toBe('重新加载');
    const unregister = mocks.register.mock.results[0].value;
    await act(async () => host.querySelector('button')!.click());
    const newFrame = host.querySelector('iframe')!;
    expect(newFrame).not.toBe(oldFrame);
    expect(unregister).toHaveBeenCalledOnce();
    expect(mocks.register).toHaveBeenCalledTimes(2);
    expect(host.textContent).toContain('正在加载原稿');
    expect(host.querySelector('[role="alert"]')).toBeNull();
    await act(async () => message(oldPeer, { event: 'ready' }));
    expect(host.textContent).not.toContain('原稿 · ONLYOFFICE');
    await act(async () => message(newFrame.contentWindow!, { event: 'ready' }));
    expect(host.textContent).toContain('原稿 · ONLYOFFICE');
    expect(host.querySelector('button')).toBeNull();
  });

  it('reports an unavailable source service without switching renderers', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: true, json: async () => ({ enabled: false }) })),
    );
    await act(async () => root.render(React.createElement(NativePptxView, { scene })));
    expect(host.querySelector('[data-native-pptx="onlyoffice"]')).not.toBeNull();
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('原稿播放服务暂不可用');
    expect(host.querySelector('button')?.textContent).toBe('重新加载');
    expect(host.textContent).not.toContain('兼容');
  });

  it('offers source retry when initialization times out', async () => {
    vi.useFakeTimers();
    try {
      await act(async () => root.render(React.createElement(NativePptxView, { scene })));
      await act(async () => vi.advanceTimersByTimeAsync(45000));
      expect(host.querySelector('[role="alert"]')?.textContent).toContain('原稿加载超时');
      expect(host.querySelector('button')?.textContent).toBe('重新加载');
      expect(host.textContent).not.toContain('兼容');
    } finally {
      vi.useRealTimers();
    }
  });
});
