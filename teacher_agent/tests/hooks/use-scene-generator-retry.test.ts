import { beforeEach, describe, expect, it, vi, type Mock } from 'vitest';
import type { SceneOutline } from '@/lib/types/generation';
import type { Scene } from '@/lib/types/stage';

const mocks = vi.hoisted(() => ({
  getCurrentModelConfig: vi.fn(),
  settingsState: vi.fn(),
  audioPut: vi.fn(),
  audioGet: vi.fn(),
  audioDelete: vi.fn(),
  poolPut: vi.fn(),
  poolReplace: vi.fn(),
  poolRemove: vi.fn(),
  isTTSProviderEnabled: vi.fn(),
  pickNarratorAgent: vi.fn(),
  resolveAgentVoiceOptions: vi.fn(),
  listAgents: vi.fn(),
}));

vi.mock('@/lib/utils/model-config', () => ({
  getCurrentModelConfig: mocks.getCurrentModelConfig,
}));

vi.mock('@/lib/store/settings', () => ({
  useSettingsStore: {
    getState: mocks.settingsState,
  },
}));

vi.mock('@/lib/utils/database', () => ({
  db: {
    audioFiles: {
      put: mocks.audioPut,
      get: mocks.audioGet,
      delete: mocks.audioDelete,
    },
  },
}));

vi.mock('@/lib/media/asset-pool', () => ({
  putAsset: mocks.poolPut,
  replaceAsset: mocks.poolReplace,
  removeAsset: mocks.poolRemove,
}));

vi.mock('@/lib/audio/provider-enablement', () => ({
  isTTSProviderEnabled: mocks.isTTSProviderEnabled,
}));

vi.mock('@/lib/audio/agent-voice', () => ({
  pickNarratorAgent: mocks.pickNarratorAgent,
  resolveAgentVoiceOptions: mocks.resolveAgentVoiceOptions,
}));

vi.mock('@/lib/orchestration/registry/store', () => ({
  useAgentRegistry: {
    getState: () => ({
      listAgents: mocks.listAgents,
    }),
  },
}));

const mockFetch = vi.fn() as Mock;
vi.stubGlobal('fetch', mockFetch);

const outline = {
  id: 'outline-1',
  type: 'slide',
  title: 'Retry Scene',
  description: 'Retry transient failures',
  keyPoints: ['retry'],
  order: 2,
} as SceneOutline;

const retryOptions = {
  maxRetries: 1,
  sleep: async () => undefined,
  random: () => 0,
};

function jsonResponse(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 429 ? 'Too Many Requests' : status === 401 ? 'Unauthorized' : 'OK',
    json: async () => body,
  };
}

describe('browser scene generation retry wrappers', () => {
  beforeEach(() => {
    mockFetch.mockReset();
    mocks.audioPut.mockReset();
    mocks.audioGet.mockReset().mockResolvedValue(undefined);
    mocks.audioDelete.mockReset().mockResolvedValue(undefined);
    mocks.poolPut.mockReset();
    mocks.poolReplace.mockReset().mockResolvedValue(undefined);
    mocks.poolRemove.mockReset().mockResolvedValue(undefined);
    mocks.poolPut.mockResolvedValue('ast_audio_allocated');
    mocks.getCurrentModelConfig.mockReturnValue({});
    mocks.settingsState.mockReturnValue({
      imageProviderId: '',
      imageProvidersConfig: {},
      imageGenerationEnabled: false,
      videoProviderId: '',
      videoProvidersConfig: {},
      videoGenerationEnabled: false,
      ttsProviderId: 'server-tts',
      ttsProvidersConfig: {
        'server-tts': {
          apiKey: 'tts-key',
          modelId: 'tts-model',
        },
      },
      ttsVoice: 'narrator',
      ttsSpeed: 1,
    });
    mocks.isTTSProviderEnabled.mockReturnValue(true);
    mocks.pickNarratorAgent.mockReturnValue(undefined);
    mocks.resolveAgentVoiceOptions.mockResolvedValue({});
    mocks.listAgents.mockReturnValue([]);
  });

  it('retries transient scene content HTTP failures before returning success', async () => {
    const { fetchSceneContent } = await import('@/lib/hooks/use-scene-generator');
    mockFetch
      .mockResolvedValueOnce(jsonResponse(429, { error: 'rate limited' }))
      .mockResolvedValueOnce(jsonResponse(200, { success: true, content: { elements: [] } }));

    const result = await fetchSceneContent(
      {
        outline,
        allOutlines: [outline],
        stageId: 'stage-1',
        stageInfo: { name: 'Retry Course' },
      },
      undefined,
      retryOptions,
    );

    expect(result).toMatchObject({ success: true, content: { elements: [] } });
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });

  it('does not retry permanent scene action HTTP failures', async () => {
    const { fetchSceneActions } = await import('@/lib/hooks/use-scene-generator');
    mockFetch.mockResolvedValue(jsonResponse(401, { error: 'unauthorized' }));

    const result = await fetchSceneActions(
      {
        outline,
        allOutlines: [outline],
        content: { elements: [] },
        stageId: 'stage-1',
      },
      undefined,
      retryOptions,
    );

    expect(result).toMatchObject({ success: false, error: 'unauthorized' });
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it('keeps semantic alignment failures failed without repeating model calls or generating audio', async () => {
    const { fetchSceneActions } = await import('@/lib/hooks/use-scene-generator');
    mockFetch.mockResolvedValue(
      jsonResponse(422, {
        success: false,
        errorCode: 'FOCUS_SPEECH_ALIGNMENT_FAILED',
        error: '讲解与聚焦校验未通过',
      }),
    );
    const result = await fetchSceneActions(
      { outline, allOutlines: [outline], content: { elements: [] }, stageId: 'stage-1' },
      undefined,
      retryOptions,
    );
    expect(result).toMatchObject({
      success: false,
      errorCode: 'FOCUS_SPEECH_ALIGNMENT_FAILED',
      statusCode: 422,
    });
    expect(mockFetch).toHaveBeenCalledTimes(1);
    expect(mocks.poolPut).not.toHaveBeenCalled();
  });

  it('preserves scene content error metadata for localized UI messages', async () => {
    const { fetchSceneContent } = await import('@/lib/hooks/use-scene-generator');
    mockFetch.mockResolvedValue(
      jsonResponse(429, {
        success: false,
        errorCode: 'RATE_LIMITED',
        error: 'Upstream rate limit reached. Please try again shortly.',
      }),
    );

    const result = await fetchSceneContent(
      {
        outline,
        allOutlines: [outline],
        stageId: 'stage-1',
        stageInfo: { name: 'Retry Course' },
      },
      undefined,
      { ...retryOptions, maxRetries: 0 },
    );

    expect(result).toMatchObject({
      success: false,
      errorCode: 'RATE_LIMITED',
      statusCode: 429,
    });
  });

  it('preserves internal scene content errors for localized fallback messages', async () => {
    const { fetchSceneContent } = await import('@/lib/hooks/use-scene-generator');
    mockFetch.mockResolvedValue(
      jsonResponse(500, {
        success: false,
        errorCode: 'INTERNAL_ERROR',
        error: 'Scene generation failed. Please try again.',
      }),
    );

    const result = await fetchSceneContent(
      {
        outline,
        allOutlines: [outline],
        stageId: 'stage-1',
        stageInfo: { name: 'Retry Course' },
      },
      undefined,
      { ...retryOptions, maxRetries: 0 },
    );

    expect(result).toMatchObject({
      success: false,
      errorCode: 'INTERNAL_ERROR',
      statusCode: 500,
    });
  });

  it('rethrows an aborted scene content request', async () => {
    const { fetchSceneContent } = await import('@/lib/hooks/use-scene-generator');
    const abort = Object.assign(new Error('Aborted'), { name: 'AbortError' });
    mockFetch.mockRejectedValueOnce(abort);

    await expect(
      fetchSceneContent(
        {
          outline,
          allOutlines: [outline],
          stageId: 'stage-1',
          stageInfo: { name: 'Retry Course' },
        },
        undefined,
        retryOptions,
      ),
    ).rejects.toBe(abort);

    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it('rethrows an aborted scene actions request', async () => {
    const { fetchSceneActions } = await import('@/lib/hooks/use-scene-generator');
    const abort = Object.assign(new Error('Aborted'), { name: 'AbortError' });
    mockFetch.mockRejectedValueOnce(abort);

    await expect(
      fetchSceneActions(
        {
          outline,
          allOutlines: [outline],
          content: { elements: [] },
          stageId: 'stage-1',
        },
        undefined,
        retryOptions,
      ),
    ).rejects.toBe(abort);

    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it('retries transient TTS failures before storing audio', async () => {
    const { generateAndStoreTTS } = await import('@/lib/hooks/use-scene-generator');
    mockFetch
      .mockResolvedValueOnce(jsonResponse(503, { error: 'provider overloaded' }))
      .mockResolvedValueOnce(
        jsonResponse(200, {
          success: true,
          base64: btoa('audio-data'),
          format: 'wav',
        }),
      );

    const assetId = await generateAndStoreTTS(
      'tts_s2_action_1',
      'Hello class',
      'English',
      undefined,
      retryOptions,
    );

    expect(assetId).toBe('ast_audio_allocated');
    expect(mockFetch).toHaveBeenCalledTimes(2);
    expect(mocks.poolPut).toHaveBeenCalledWith(
      expect.any(Blob),
      expect.objectContaining({
        contentType: 'audio/wav',
        mediaType: 'audio',
        text: 'Hello class',
        voice: 'narrator',
      }),
    );
    expect(mocks.audioPut).toHaveBeenCalledWith(
      expect.objectContaining({
        id: 'ast_audio_allocated',
        format: 'wav',
      }),
    );
  });

  it('does not write Dexie when pool allocation fails', async () => {
    const { generateAndStoreTTS } = await import('@/lib/hooks/use-scene-generator');
    mockFetch.mockResolvedValue(
      jsonResponse(200, {
        success: true,
        base64: btoa('audio-data'),
        format: 'wav',
      }),
    );
    mocks.poolPut.mockRejectedValueOnce(new Error('pool unavailable'));

    await expect(generateAndStoreTTS('request-1', 'Hello class')).rejects.toThrow(
      'pool unavailable',
    );
    expect(mocks.audioPut).not.toHaveBeenCalled();
  });

  it('does not report an allocated id when the compatibility write fails', async () => {
    const { generateAndStoreTTS } = await import('@/lib/hooks/use-scene-generator');
    mockFetch.mockResolvedValue(
      jsonResponse(200, {
        success: true,
        base64: btoa('audio-data'),
        format: 'wav',
      }),
    );
    mocks.audioPut.mockRejectedValueOnce(new Error('Dexie unavailable'));

    await expect(generateAndStoreTTS('request-1', 'Hello class')).rejects.toThrow(
      'Dexie unavailable',
    );
    expect(mocks.poolPut).toHaveBeenCalledOnce();
    expect(mocks.poolRemove).toHaveBeenCalledExactlyOnceWith('ast_audio_allocated');
  });

  it('preserves successful clips on partial synthesis and does not report a complete duration', async () => {
    const { generateTTSForScene } = await import('@/lib/hooks/use-scene-generator');
    mocks.poolPut.mockResolvedValueOnce('ast_first_audio');
    mockFetch
      .mockResolvedValueOnce(
        jsonResponse(200, {
          success: true,
          base64: btoa('first-audio'),
          format: 'wav',
        }),
      )
      .mockResolvedValueOnce(jsonResponse(401, { error: 'second speech rejected' }));
    const scene = {
      id: 'scene-1',
      stageId: 'stage-1',
      type: 'slide',
      title: 'Scene',
      order: 1,
      content: { type: 'slide', canvas: { id: 'slide-1', elements: [] } },
      actions: [
        { id: 'speech-1', type: 'speech', text: 'First line' },
        { id: 'speech-2', type: 'speech', text: 'Second line' },
      ],
    } as unknown as Parameters<typeof generateTTSForScene>[0];

    const result = await generateTTSForScene(scene, 'English', undefined, {
      ...retryOptions,
      maxRetries: 0,
    });

    // Current main deliberately keeps playable clips when another clip fails.
    expect(result).toMatchObject({ success: true, failedCount: 1 });
    expect(mocks.poolRemove).not.toHaveBeenCalled();
    expect(mocks.audioDelete).not.toHaveBeenCalled();
    expect(scene.actions?.[0]).toMatchObject({ audioId: 'ast_first_audio' });
    expect(scene.actions?.[1]).not.toHaveProperty('audioId');
    expect(scene.timing?.measuredDurationSec).toBeUndefined();
  });

  it('waits for parallel TTS workers before rolling back an abandoned scene', async () => {
    const { generateTTSForScene } = await import('@/lib/hooks/use-scene-generator');
    mocks.settingsState.mockReturnValue({
      ...mocks.settingsState(),
      parallelSceneConcurrency: 2,
    });
    const abort = Object.assign(new Error('Aborted'), { name: 'AbortError' });
    let releaseSibling!: () => void;
    const siblingMayFinish = new Promise<void>((resolve) => {
      releaseSibling = resolve;
    });
    mockFetch.mockRejectedValueOnce(abort).mockImplementationOnce(async () => {
      await siblingMayFinish;
      return jsonResponse(200, {
        success: true,
        base64: btoa('late-audio'),
        format: 'wav',
      });
    });
    mocks.poolPut.mockResolvedValueOnce('ast_late_audio');
    const scene = {
      id: 'scene-1',
      stageId: 'stage-1',
      type: 'slide',
      title: 'Scene',
      order: 1,
      content: { type: 'slide', canvas: { id: 'slide-1', elements: [] } },
      actions: [
        { id: 'speech-1', type: 'speech', text: 'Aborted line' },
        { id: 'speech-2', type: 'speech', text: 'Late line' },
      ],
    } as unknown as Parameters<typeof generateTTSForScene>[0];

    const generating = generateTTSForScene(scene, 'English', undefined, retryOptions);
    await vi.waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(2));
    expect(mocks.poolRemove).not.toHaveBeenCalled();

    releaseSibling();
    await expect(generating).rejects.toBe(abort);

    expect(mocks.poolRemove).toHaveBeenCalledExactlyOnceWith('ast_late_audio');
    expect(mocks.audioDelete).toHaveBeenCalledExactlyOnceWith('ast_late_audio');
    expect(scene.actions?.every((action) => !('audioId' in action))).toBe(true);
  });

  it.each([false, true])(
    'calibrates aggregate audio and protects navigation during synthesis (navigate=%s)',
    async (navigate) => {
      const { calibrateCompletedCourse } = await import('@/lib/hooks/use-scene-generator');
      const { useStageStore } = await import('@/lib/store/stage');
      const { assessCourseDuration } = await import('@/lib/generation/course-duration');
      const pages = [60, 85, 60].map(
        (actual, index) =>
          ({
            id: `page-${index}`,
            stageId: 'stage-1',
            type: 'slide',
            title: 'Example',
            order: index,
            content: { type: 'slide', canvas: { elements: [] } },
            actions: [
              {
                id: `speech-${index}`,
                type: 'speech',
                text: '保留这个知识点和推演。',
                audioId: `old-${index}`,
              },
            ],
            timing: { plannedDurationSec: 60, measuredDurationSec: actual },
          }) as unknown as Scene,
      );
      const state = {
        stage: {
          id: 'stage-1',
          timing: {
            budgetVersion: 1,
            targetDurationMinutes: 3,
            expectedAutomaticPages: 3,
            courseCorrectionAttempts: 0,
          },
        },
        scenes: pages,
        outlines: [],
        currentSceneId: 'page-0',
        mode: 'play',
        generationEpoch: 1,
        generationStatus: 'completed',
        generatingOutlines: [],
        failedOutlines: [],
        setGenerationStatus: vi.fn((status: string) => {
          state.generationStatus = status;
        }),
        updateStage: vi.fn((update: { timing: typeof state.stage.timing }) => {
          state.stage.timing = update.timing;
        }),
        updateScene: vi.fn((id: string, update: Partial<Scene>) => {
          state.scenes = state.scenes.map((scene) =>
            scene.id === id ? ({ ...scene, ...update } as Scene) : scene,
          );
        }),
        saveToStorage: vi.fn().mockResolvedValue(undefined),
      };
      const spy = vi
        .spyOn(useStageStore, 'getState')
        .mockImplementation(() => state as unknown as ReturnType<typeof useStageStore.getState>);
      mocks.audioGet.mockResolvedValue({ duration: 60 });
      mockFetch.mockImplementation(async (url: string) => {
        if (url.includes('scene-actions'))
          return jsonResponse(200, {
            success: true,
            scene: {
              actions: [
                { id: 'speech-1', type: 'speech', text: '重新解释相同知识点，保留步骤和结论。' },
              ],
            },
          });
        if (navigate) state.currentSceneId = 'page-1';
        return jsonResponse(200, { success: true, base64: btoa('measured-audio'), format: 'wav' });
      });
      try {
        if (navigate) {
          await expect(calibrateCompletedCourse()).rejects.toMatchObject({ name: 'AbortError' });
          expect(state.scenes).toBe(pages);
          expect(mocks.poolRemove).toHaveBeenCalledExactlyOnceWith('ast_audio_allocated');
        } else {
          await expect(calibrateCompletedCourse()).resolves.toEqual({ attempts: 1, changed: 1 });
          expect(assessCourseDuration(state.scenes, 3, 3).actualSeconds).toBe(180);
          expect(state.scenes[1].content).toBe(pages[1].content);
          expect(state.scenes[0]).toBe(pages[0]);
          expect(state.scenes[2]).toBe(pages[2]);
          expect(state.saveToStorage).toHaveBeenCalledOnce();
          expect(mocks.poolRemove).not.toHaveBeenCalled();
          await expect(calibrateCompletedCourse()).resolves.toEqual({ attempts: 0, changed: 0 });
        }
        expect(state.stage.timing.courseCorrectionAttempts).toBe(1);
        expect(state.generationStatus).toBe('completed');
        expect(mockFetch).toHaveBeenCalledTimes(2);
        const ttsRequest = JSON.parse(mockFetch.mock.calls[1][1].body);
        expect(ttsRequest.audioId).not.toBe('tts_s1_speech-1');
        expect(ttsRequest.ttsSpeed).toBe(1);
        expect(
          JSON.parse(mockFetch.mock.calls[0][1].body).durationFeedback.courseMeasuredSeconds,
        ).toBe(205);
      } finally {
        spy.mockRestore();
      }
    },
  );

  it('replaces allocated audio under the stable id and refreshes its compatibility row', async () => {
    const { generateAndStoreTTS } = await import('@/lib/hooks/use-scene-generator');
    mockFetch.mockResolvedValue(
      jsonResponse(200, {
        success: true,
        base64: btoa('replacement-audio'),
        format: 'wav',
      }),
    );

    await expect(
      generateAndStoreTTS(
        'request-1',
        'Updated class',
        'English',
        undefined,
        undefined,
        'ast_stable_audio',
      ),
    ).resolves.toBe('ast_stable_audio');

    expect(mocks.poolPut).not.toHaveBeenCalled();
    expect(mocks.poolReplace).toHaveBeenCalledExactlyOnceWith(
      'ast_stable_audio',
      expect.any(Blob),
      expect.objectContaining({ mediaType: 'audio', text: 'Updated class' }),
    );
    expect(mocks.audioPut).toHaveBeenCalledExactlyOnceWith(
      expect.objectContaining({ id: 'ast_stable_audio', format: 'wav' }),
    );
  });
});
