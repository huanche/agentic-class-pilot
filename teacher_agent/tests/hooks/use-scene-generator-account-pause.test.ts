// @vitest-environment jsdom
import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({
  state: {} as Record<string, unknown>,
  settings: {} as Record<string, unknown>,
  fallback: vi.fn(),
}));
vi.mock('@/lib/store/stage', () => ({
  useStageStore: { getState: () => mocks.state },
  markStagePersistenceDirty: vi.fn(),
}));
vi.mock('@/lib/store/settings', () => ({ useSettingsStore: { getState: () => mocks.settings } }));
vi.mock('@/lib/utils/database', () => ({
  db: {
    courseGovernance: { get: async () => ({ enabled: true }) },
    audioFiles: { get: vi.fn(), put: vi.fn(), delete: vi.fn() },
  },
}));
vi.mock('@/lib/utils/model-config', () => ({ getCurrentModelConfig: () => ({}) }));
vi.mock('@/lib/media/media-orchestrator', () => ({
  generateMediaForOutlines: async () => {},
  reconcileCompletedMediaForScene: vi.fn(),
}));
vi.mock('@/lib/course-governance/governance', () => ({
  createAutomaticFallbackScene: vi.fn(),
  recordAutomaticFallback: mocks.fallback,
}));
vi.mock('@/lib/media/asset-pool', () => ({
  putAsset: vi.fn(),
  removeAsset: vi.fn(),
  replaceAsset: vi.fn(),
}));
vi.mock('@/lib/audio/provider-enablement', () => ({ isTTSProviderEnabled: () => true }));
vi.mock('@/lib/audio/agent-voice', () => ({
  pickNarratorAgent: () => undefined,
  resolveAgentVoiceOptions: async () => ({}),
}));
vi.mock('@/lib/orchestration/registry/store', () => ({
  useAgentRegistry: { getState: () => ({ listAgents: () => [] }) },
}));
import { useSceneGenerator } from '@/lib/hooks/use-scene-generator';

describe('account errors pause the real generation hook with governance enabled', () => {
  let host: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;
  let api: ReturnType<typeof useSceneGenerator>;
  const failed = vi.fn();
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
    const state = {
      stage: { id: 'lesson', name: 'Python' },
      scenes: [{ id: 'saved', stageId: 'lesson', order: 1, actions: [] }],
      outlines: [1, 2, 3, 4, 5, 6].map((order) => ({
        id: `outline-${order}`,
        order,
        type: 'slide',
        title: `Page ${order}`,
        keyPoints: [],
      })),
      generatingOutlines: [] as unknown[],
      failedOutlines: [] as unknown[],
      generationEpoch: 1,
      status: 'idle',
      setGenerationStatus: (status: string) => {
        state.status = status;
      },
      setGeneratingOutlines: (items: unknown[]) => {
        state.generatingOutlines = items;
      },
      addFailedOutline: (outline: unknown) => {
        state.failedOutlines.push(outline);
      },
      setCurrentGeneratingOrder: vi.fn(),
      bumpGenerationEpoch: () => {
        state.generationEpoch++;
      },
      addScene: vi.fn(),
    };
    mocks.state = state;
    mocks.settings = {
      ttsEnabled: true,
      ttsProviderId: 'qwen-tts',
      ttsVoice: 'Cherry',
      ttsProvidersConfig: { 'qwen-tts': { apiKey: 'test-key' } },
      parallelSceneConcurrency: 0,
    };
    host = document.createElement('div');
    document.body.append(host);
    root = createRoot(host);
  });
  afterEach(async () => {
    api?.stop();
    await act(async () => root.unmount());
    host.remove();
    vi.unstubAllGlobals();
  });
  it.each([0, 2])(
    'pauses without fallback, completed-scene loss, or continued prefetch (concurrency=%s)',
    async (concurrency) => {
      mocks.settings.parallelSceneConcurrency = concurrency;
      const pendingSignals: AbortSignal[] = [];
      const requestedOrders: number[] = [];
      const fetchMock = vi.fn(async (url: string, init: RequestInit) => {
        const body = JSON.parse(String(init.body));
        if (url.endsWith('/scene-content')) {
          requestedOrders.push(body.outline.order);
          if (body.outline.order !== 2)
            return new Promise<Response>((_resolve, reject) => {
              const signal = init.signal as AbortSignal;
              pendingSignals.push(signal);
              signal.addEventListener(
                'abort',
                () => reject(new DOMException('Aborted', 'AbortError')),
                { once: true },
              );
            });
          return Response.json({
            success: true,
            content: { type: 'slide', canvas: { id: 'canvas', elements: [] } },
          });
        }
        if (url.endsWith('/scene-actions'))
          return Response.json({
            success: true,
            scene: {
              id: 'new',
              stageId: 'lesson',
              order: 2,
              type: 'slide',
              title: 'Page 2',
              content: { type: 'slide', canvas: { id: 'canvas', elements: [] } },
              actions: [{ id: 'speech-1', type: 'speech', text: 'Narration one' }],
            },
          });
        if (url.endsWith('/tts'))
          return Response.json(
            {
              success: false,
              errorCode: 'TTS_PROVIDER_ACCOUNT_UNAVAILABLE',
              error: '配音账户欠费，已暂停生成。',
            },
            { status: 402 },
          );
        throw new Error('Unexpected request');
      });
      vi.stubGlobal('fetch', fetchMock);
      function Harness() {
        api = useSceneGenerator({ onSceneFailed: failed });
        return null;
      }
      await act(async () => {
        root.render(createElement(Harness));
      });
      await act(async () => {
        await api.generateRemaining({ stageInfo: { name: 'Python' }, preferServerModel: true });
      });
      expect(mocks.state.status).toBe('paused');
      expect(mocks.state.scenes).toMatchObject([{ id: 'saved', order: 1 }]);
      expect(mocks.state.failedOutlines).toMatchObject([{ id: 'outline-2' }]);
      expect(mocks.fallback).not.toHaveBeenCalled();
      expect(failed).toHaveBeenCalledWith(
        expect.objectContaining({ order: 2 }),
        '配音账户欠费，已暂停生成。',
      );
      expect(fetchMock.mock.calls.filter(([url]) => url.endsWith('/tts'))).toHaveLength(1);
      if (concurrency === 2) {
        expect(pendingSignals.length).toBeGreaterThan(0);
        expect(pendingSignals.every((signal) => signal.aborted)).toBe(true);
        expect(requestedOrders).not.toContain(5);
      }
    },
  );
});
