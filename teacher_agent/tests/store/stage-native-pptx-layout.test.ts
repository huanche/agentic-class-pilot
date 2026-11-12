import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Scene, Stage } from '@/lib/types/stage';

vi.mock('@/lib/utils/stage-storage', () => ({
  saveStageDataIncremental: vi.fn().mockResolvedValue(undefined),
  saveStageData: vi.fn().mockResolvedValue(undefined),
}));
import { useStageStore } from '@/lib/store/stage';
import { nativePptxPage } from '@/lib/onlyoffice/native-player';

beforeEach(() => {
  vi.useFakeTimers();
  useStageStore.setState({
    stage: { id: 'layout-stage', nativePptx: { pages: { source5: 5 } } } as unknown as Stage,
    scenes: [
      {
        id: 'layout-scene',
        stageId: 'layout-stage',
        outlineId: 'source5',
        type: 'slide',
        title: '指针',
        order: 1,
        content: {
          type: 'slide',
          canvas: {
            id: 'source',
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
                id: 'address',
                type: 'text',
                left: 10,
                top: 10,
                width: 50,
                height: 20,
                content: '2000',
                defaultFontName: 'Arial',
                defaultColor: '#000',
                rotate: 0,
              },
            ],
          },
        },
      },
    ] as Scene[],
    currentSceneId: 'layout-scene',
  });
});
afterEach(async () => {
  await vi.runOnlyPendingTimersAsync();
  useStageStore.getState().clearStore();
  vi.useRealTimers();
});

describe('native PPTX edit provenance', () => {
  it('does not treat JSON property ordering from database hydration as an edit', () => {
    const content = structuredClone(useStageStore.getState().scenes[0].content);
    if (content.type !== 'slide') throw new Error('not a slide');
    const { theme, ...rest } = content.canvas;
    content.canvas = { theme, ...rest };
    useStageStore.getState().updateScene('layout-scene', { content });
    expect(useStageStore.getState().scenes[0].nativePptxEdited).toBeUndefined();
  });
  it('retains the native source after automatic text measurement but falls back after a real edit', () => {
    const content = structuredClone(useStageStore.getState().scenes[0].content);
    if (content.type !== 'slide') throw new Error('not a slide');
    if (content.canvas.elements[0].type !== 'text') throw new Error('not text');
    content.canvas.elements[0].height = 43;
    useStageStore.getState().updateScene('layout-scene', { content }, { source: 'layout' });
    let state = useStageStore.getState();
    expect(state.scenes[0].nativePptxEdited).toBeUndefined();
    expect(nativePptxPage(state.stage, state.scenes[0])).toBe(5);

    const edited = structuredClone(content);
    if (edited.canvas.elements[0].type !== 'text') throw new Error('not text');
    edited.canvas.elements[0].left = 123;
    useStageStore.getState().updateScene('layout-scene', { content: edited });
    state = useStageStore.getState();
    expect(state.scenes[0].nativePptxEdited).toBe(true);
    expect(nativePptxPage(state.stage, state.scenes[0])).toBeUndefined();

    edited.canvas.elements[0].height = 50;
    useStageStore.getState().updateScene('layout-scene', { content: edited }, { source: 'layout' });
    expect(useStageStore.getState().scenes[0].nativePptxEdited).toBe(true);
  });
});
