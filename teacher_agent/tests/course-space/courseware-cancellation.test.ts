// @vitest-environment jsdom
import { act, createElement, Fragment } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CoursewareGenerationButton } from '@/components/course-space/courseware-generation-button';
import {
  isGenerationTaskActive,
  useCourseGenerationTask,
} from '@/lib/store/course-generation-task';
import type { CourseSpace } from '@/lib/course-space';
import GenerationPreviewPage from '@/app/generation-preview/preview-runtime';

const preview = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: preview.push }),
  usePathname: () => '/generation-preview',
}));
vi.mock('@/lib/hooks/use-i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }));
vi.mock('@/lib/audio/voxcpm-voices', () => ({ useVoxCPMVoiceProfiles: () => ({ profiles: [] }) }));
vi.mock('@/lib/hooks/use-scene-generator', () => ({
  fetchSceneActions: vi.fn(),
  fetchSceneContent: vi.fn(),
  generateTTSForScene: vi.fn(),
}));
vi.mock('@/lib/utils/image-storage', () => ({
  loadImageMapping: vi.fn(),
  loadDocumentBlob: vi.fn(),
  cleanupOldImages: async () => {},
  storeImages: vi.fn(),
}));
vi.mock('@/components/generation/outlines-editor', () => ({
  OutlinesEditor: ({ onBack, backLabel }: { onBack: () => void; backLabel?: string }) =>
    createElement('button', { onClick: onBack }, backLabel || '返回修改需求'),
}));
vi.mock('@/components/agent/agent-reveal-modal', () => ({ AgentRevealModal: () => null }));

vi.mock('next/link', () => ({ default: 'a' }));
vi.mock('@/components/ui/popover', () => ({
  Popover: ({ children }: { children: React.ReactNode }) => createElement(Fragment, null, children),
  PopoverTrigger: ({ children }: { children: React.ReactNode }) => children,
  PopoverContent: ({ children }: { children: React.ReactNode }) =>
    createElement('div', null, children),
}));

describe('courseware cancellation before server submission', () => {
  let host: HTMLDivElement;
  let root: Root;
  beforeEach(() => {
    vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
    host = document.createElement('div');
    document.body.append(host);
    root = createRoot(host);
    useCourseGenerationTask.setState({ task: null, runtimeId: null });
    sessionStorage.clear();
    preview.push.mockClear();
  });
  afterEach(async () => {
    await act(async () => root.unmount());
    host.remove();
    vi.unstubAllGlobals();
  });
  it('offers cancellation while waiting for outline confirmation without a server job', async () => {
    const fetch = vi.fn();
    vi.stubGlobal('fetch', fetch);
    sessionStorage.setItem('generationSession', JSON.stringify({ sessionId: 'outline-review' }));
    useCourseGenerationTask.getState().setTask({
      id: 'outline-review',
      courseId: 'python',
      title: 'Python',
      status: 'review',
      message: '等待教师审核',
      step: 1,
      total: 3,
    });
    function WorkspaceButton() {
      const task = useCourseGenerationTask((state) => state.task);
      return createElement(CoursewareGenerationButton, {
        course: {
          id: 'python',
          title: 'Python',
          status: 'active',
          modules: [],
        } as unknown as CourseSpace,
        lessonId: 'lesson',
        jobs: [],
        generationLocked: isGenerationTaskActive(task),
        onGenerate: vi.fn(),
        onRefresh: vi.fn(async () => {}),
        onOpenResult: vi.fn(),
      });
    }
    await act(async () => root.render(createElement(WorkspaceButton)));
    expect(host.textContent).toContain('等待确认');
    const resume = Array.from(host.querySelectorAll('a')).find(
      (link) => link.textContent === '继续确认',
    );
    expect(resume?.getAttribute('href')).toBe('/generation-preview');
    const cancel = Array.from(host.querySelectorAll('button')).find(
      (b) => b.textContent === '取消任务',
    );
    expect(cancel).toBeDefined();
    await act(async () => cancel!.click());
    expect(isGenerationTaskActive(useCourseGenerationTask.getState().task)).toBe(false);
    expect(sessionStorage.getItem('generationSession')).toBeNull();
    expect(fetch).not.toHaveBeenCalled();
    expect(
      Array.from(host.querySelectorAll('button')).find((b) => b.textContent?.includes('生成课件'))
        ?.disabled,
    ).toBe(false);
  });
  it('cancels the actual restored outline-review runtime and clears its saved session', async () => {
    const id = 'restored-outline-review';
    sessionStorage.setItem(
      'generationSession',
      JSON.stringify({
        sessionId: id,
        previewPhase: 'review',
        requirements: { requirement: 'Python', targetDurationMinutes: 1 },
        courseSpaceContext: { courseId: 'python', scope: { type: 'lesson', lessonId: 'lesson' } },
        sceneOutlines: [
          {
            id: 'page1',
            order: 1,
            type: 'slide',
            title: 'Python',
            description: 'Introduction',
            keyPoints: ['print'],
          },
        ],
      }),
    );
    useCourseGenerationTask.getState().setRuntimeId(id);
    await act(async () => root.render(createElement(GenerationPreviewPage)));
    expect(useCourseGenerationTask.getState().task?.status).toBe('review');
    expect(useCourseGenerationTask.getState().task?.url).toBe('/generation-preview');
    const cancel = Array.from(host.querySelectorAll('button')).find(
      (b) => b.textContent === '取消生成',
    );
    expect(cancel).toBeDefined();
    await act(async () => cancel!.click());
    expect(useCourseGenerationTask.getState().task?.status).toBe('cancelled');
    expect(useCourseGenerationTask.getState().runtimeId).toBeNull();
    expect(sessionStorage.getItem('generationSession')).toBeNull();
    expect(preview.push).toHaveBeenCalledWith('/course-space?workspace=python');
  });
});
