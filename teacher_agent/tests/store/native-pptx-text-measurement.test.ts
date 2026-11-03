// @vitest-environment jsdom
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import type { PPTTextElement } from '@openmaic/dsl';
import type { Scene, Stage } from '@/lib/types/stage';

vi.mock('@/lib/utils/stage-storage', () => ({
  saveStageDataIncremental: vi.fn().mockResolvedValue(undefined),
  saveStageData: vi.fn().mockResolvedValue(undefined),
}));
vi.mock('@/lib/hooks/use-history-snapshot', () => ({
  useHistorySnapshot: () => ({ addHistorySnapshot: vi.fn() }),
}));
vi.mock('@/components/slide-renderer/components/element/ElementOutline', () => ({
  ElementOutline: () => null,
}));
vi.mock('@/components/slide-renderer/components/element/ProsemirrorEditor', () => ({
  ProsemirrorEditor: () => null,
}));

import { useStageStore } from '@/lib/store/stage';
import { SceneProvider } from '@/lib/contexts/scene-context';
import { TextElement } from '@/components/slide-renderer/components/element/TextElement';
import { nativePptxPage } from '@/lib/onlyoffice/native-player';

let host: HTMLDivElement;
let root: Root;
let observers: Set<ResizeObserverCallback>;
function MeasuredText() {
  const scene = useStageStore((s) => s.scenes[0]);
  if (scene.content.type !== 'slide') return null;
  return React.createElement(TextElement, {
    elementInfo: scene.content.canvas.elements[0] as PPTTextElement,
  });
}
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  observers = new Set();
  vi.stubGlobal(
    'ResizeObserver',
    class {
      constructor(readonly callback: ResizeObserverCallback) {}
      observe() {
        observers.add(this.callback);
      }
      unobserve() {
        observers.delete(this.callback);
      }
      disconnect() {
        observers.delete(this.callback);
      }
    },
  );
  useStageStore.setState({
    stage: { id: 'measure', nativePptx: { pages: { page5: 5 } } } as unknown as Stage,
    scenes: [
      {
        id: 'measured',
        stageId: 'measure',
        outlineId: 'page5',
        title: '2000',
        order: 1,
        type: 'slide',
        content: {
          type: 'slide',
          canvas: {
            id: 'slide',
            viewportSize: 1000,
            viewportRatio: 0.75,
            theme: {
              backgroundColor: '#fff',
              themeColors: [],
              fontColor: '#000',
              fontName: 'Arial',
            },
            elements: [
              {
                id: 'text',
                type: 'text',
                content: '2000',
                left: 10,
                top: 20,
                width: 70,
                height: 25,
                rotate: 0,
                defaultFontName: 'Arial',
                defaultColor: '#000',
              },
            ],
          },
        },
      },
    ] as Scene[],
    currentSceneId: 'measured',
  });
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  useStageStore.getState().clearStore();
  vi.unstubAllGlobals();
});

it.each([false, true])(
  'keeps the native source after actual TextElement observer writes (vertical=%s)',
  async (vertical) => {
    const scene = structuredClone(useStageStore.getState().scenes[0]);
    if (scene.content.type !== 'slide') throw Error('not slide');
    (scene.content.canvas.elements[0] as PPTTextElement).vertical = vertical;
    useStageStore.setState({ scenes: [scene] });
    await act(async () =>
      root.render(React.createElement(SceneProvider, null, React.createElement(MeasuredText))),
    );
    expect(observers.size).toBeGreaterThan(0);
    await act(async () => {
      for (const callback of [...observers])
        callback(
          [{ contentRect: { height: 42, width: 34 } } as ResizeObserverEntry],
          {} as ResizeObserver,
        );
    });
    let state = useStageStore.getState();
    expect(state.scenes[0].nativePptxEdited).toBeUndefined();
    expect(nativePptxPage(state.stage, state.scenes[0])).toBe(5);
    const measured = structuredClone(state.scenes[0].content);
    if (measured.type !== 'slide') throw Error('not slide');
    const text = measured.canvas.elements[0];
    if (text.type !== 'text') throw Error('not text');
    expect(text[vertical ? 'width' : 'height']).toBe(vertical ? 54 : 62);
    // A real one-dimensional resize must still select the edited canvas.
    text.height += 10;
    await act(async () => useStageStore.getState().updateScene('measured', { content: measured }));
    state = useStageStore.getState();
    expect(state.scenes[0].nativePptxEdited).toBe(true);
    expect(nativePptxPage(state.stage, state.scenes[0])).toBeUndefined();
  },
);
