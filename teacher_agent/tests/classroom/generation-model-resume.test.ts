// @vitest-environment jsdom
import { act, createElement, type ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  generate: vi.fn(async (_params: unknown) => {}),
  stop: vi.fn(),
  retry: vi.fn(),
  load: vi.fn(async () => {}),
  update: vi.fn(),
  fetch: vi.fn(),
  sync: vi.fn(),
  run: vi.fn(),
  serverRead: false,
  allowSync: false,
  pending: false,
  from: '',
  stage: {} as Record<string, unknown>,
  onFailure: undefined as undefined | ((outline: { title: string }, reason: string) => void),
}));
const state = {
  stage: mocks.stage,
  scenes: [{ id: 'first', stageId: 'lesson', order: 1 }],
  outlines: [
    { id: 'one', order: 1 },
    { id: 'two', order: 2 },
  ],
  generationComplete: false,
  loadFromStorage: mocks.load,
  updateStage: mocks.update,
};
vi.mock('@/lib/store', () => {
  const store = Object.assign(
    (selector?: (s: typeof state) => unknown) => (selector ? selector(state) : state),
    {
      getState: () => state,
      setState: vi.fn(),
    },
  );
  return { useStageStore: store };
});
vi.mock('@/components/stage', () => ({
  Stage: () => createElement('div', null, 'classroom ready'),
}));
vi.mock('@/lib/hooks/use-theme', () => ({
  ThemeProvider: ({ children }: { children: ReactNode }) => children,
}));
vi.mock('@/lib/contexts/media-stage-context', () => ({
  MediaStageProvider: ({ children }: { children: ReactNode }) => children,
}));
vi.mock('next/link', () => ({
  default: ({ children }: { children: ReactNode }) => createElement('span', null, children),
}));
vi.mock('next/navigation', () => ({
  useParams: () => ({ id: 'lesson' }),
  usePathname: () => '/classroom/lesson',
  useSearchParams: () => new URLSearchParams(mocks.from ? { from: mocks.from } : {}),
}));
vi.mock('@/lib/hooks/use-scene-generator', () => ({
  useSceneGenerator: (options: { onSceneFailed: typeof mocks.onFailure }) => {
    mocks.onFailure = options.onSceneFailed;
    return {
      generateRemaining: mocks.generate,
      stop: mocks.stop,
      retrySingleOutline: mocks.retry,
    };
  },
}));
vi.mock('@/lib/store/stage', () => ({
  claimStageSceneLoadToken: () => ({}),
  isCurrentStageSceneLoadToken: () => true,
}));
vi.mock('@/lib/store/settings', () => ({ useSettingsStore: { getState: () => ({}) } }));
vi.mock('@/lib/utils/image-storage', () => ({ loadImageMapping: async () => ({}) }));
vi.mock('@/lib/import/pptx-course', () => ({
  loadImportedPptSlides: async () => undefined,
  removeImportedPptSlides: vi.fn(),
}));
vi.mock('@/lib/store/media-generation', () => ({
  useMediaGenerationStore: { getState: () => ({ revokeObjectUrls: vi.fn() }), setState: vi.fn() },
}));
vi.mock('@/lib/store/whiteboard-history', () => ({
  useWhiteboardHistoryStore: { getState: () => ({ clearHistory: vi.fn() }) },
}));
vi.mock('@/lib/orchestration/registry/store', () => ({
  useAgentRegistry: { getState: () => ({}) },
}));
vi.mock('@/lib/media/media-orchestrator', () => ({
  generateMediaForOutlines: vi.fn(async () => {}),
}));
vi.mock('@/lib/learning-skills/enhanced-courseware-quality', () => ({
  isIncompleteEnhancedScene: () => false,
}));
vi.mock('@/lib/classroom/classroom-server-sync', () => ({
  canSyncClassroomSnapshot: () => mocks.allowSync,
  createClassroomSnapshotSyncQueue: () => ({ enqueue: mocks.sync, dispose: vi.fn() }),
}));
vi.mock('@/lib/classroom/load-classroom', () => ({
  defaultClassroomLoadDeps: { fetchClassroom: mocks.fetch },
  hasPendingClassroomGeneration: () => mocks.pending,
  applyClassroomStageAndScenes: vi.fn(),
  fetchClassroomForPlayer: vi.fn(),
  runClassroomLoad: async (args: {
    setLoading: (loading: boolean) => void;
    fetchClassroom: (...args: unknown[]) => Promise<unknown>;
  }) => {
    mocks.run();
    if (mocks.serverRead) {
      const result = await args.fetchClassroom('lesson');
      if (result) Object.assign(state, result);
    }
    args.setLoading(false);
  },
}));
import ClassroomDetailPage from '@/app/classroom/[id]/page';

describe('classroom generation model survives session loss', () => {
  let host: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;
  beforeEach(() => {
    vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
    vi.clearAllMocks();
    sessionStorage.clear();
    mocks.from = '';
    mocks.serverRead = false;
    mocks.allowSync = false;
    mocks.pending = false;
    state.stage = { id: 'lesson', name: 'Python' };
    state.scenes = [{ id: 'first', stageId: 'lesson', order: 1 }];
    state.outlines = [
      { id: 'one', order: 1 },
      { id: 'two', order: 2 },
    ];
    host = document.createElement('div');
    document.body.append(host);
    root = createRoot(host);
  });
  afterEach(async () => {
    await act(async () => root.unmount());
    host.remove();
    vi.unstubAllGlobals();
  });
  async function render() {
    await act(async () => {
      root.render(createElement(ClassroomDetailPage));
    });
    expect(mocks.generate).toHaveBeenCalledOnce();
    return mocks.generate.mock.calls[0]?.[0] as unknown as { preferServerModel: boolean };
  }
  it('does not echo a clean server refresh, and still saves a subsequent teacher edit', async () => {
    mocks.serverRead = true;
    mocks.allowSync = true;
    state.outlines.push({ id: 'three', order: 3 });
    mocks.fetch.mockResolvedValue({
      stage: state.stage,
      scenes: [...state.scenes, { id: 'second', stageId: 'lesson', order: 2 }],
      serverSnapshot: true,
    });
    await render();
    expect(mocks.sync).not.toHaveBeenCalled();
    state.scenes = state.scenes.map((scene) => ({ ...scene }));
    await act(async () => root.render(createElement(ClassroomDetailPage)));
    expect(mocks.sync).toHaveBeenCalledOnce();
  });

  it('offers an explicit progress refresh for a legacy partial deck with no local plan', async () => {
    mocks.pending = true;
    state.outlines = [];
    await act(async () => root.render(createElement(ClassroomDetailPage)));
    expect(host.textContent).toContain('当前显示 1 页');
    const button = [...host.querySelectorAll('button')].find(
      (node) => node.textContent === '刷新生成进度',
    );
    expect(button).toBeDefined();
    await act(async () => button!.click());
    expect(mocks.run).toHaveBeenCalledTimes(2);
  });
  it('uses the server model for a course workspace after sessionStorage was lost', async () => {
    mocks.from = '/course-space?workspace=course';
    expect((await render()).preferServerModel).toBe(true);
    expect(mocks.update).toHaveBeenCalledWith({ generationModelPolicy: 'server' });
  });
  it('keeps a persisted server policy when a bare classroom URL is reopened', async () => {
    state.stage = { ...state.stage, generationModelPolicy: 'server' };
    expect((await render()).preferServerModel).toBe(true);
  });
  it('retains the standalone browser-model flow', async () => {
    expect((await render()).preferServerModel).toBe(false);
  });
  it('respects an explicit persisted browser policy', async () => {
    state.stage = { ...state.stage, generationModelPolicy: 'browser' };
    mocks.from = '/course-space?workspace=course';
    expect((await render()).preferServerModel).toBe(false);
  });
  it('keeps a same-tab server preference', async () => {
    sessionStorage.setItem('generationParams', JSON.stringify({ preferServerModel: true }));
    expect((await render()).preferServerModel).toBe(true);
  });
  it('does not infer a course context from an external return URL', async () => {
    mocks.from = 'https://outside.example/course-space?workspace=course';
    expect((await render()).preferServerModel).toBe(false);
  });
  it('keeps completed classroom visible with a persistent generation error', async () => {
    await render();
    await act(async () =>
      mocks.onFailure?.({ title: '命令行与 REPL' }, '配音服务账户欠费，已暂停生成。'),
    );
    expect(host.querySelector('[role="alert"]')?.textContent).toContain(
      '配音服务账户欠费，已暂停生成。',
    );
    expect(host.textContent).toContain('classroom ready');
  });
});
