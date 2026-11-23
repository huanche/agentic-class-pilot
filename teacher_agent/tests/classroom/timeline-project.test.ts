import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ClassroomVideoPlan } from '@/lib/classroom-video/types';

const mocks = vi.hoisted(() => ({ snapshot: vi.fn(), pack: vi.fn() }));
vi.mock('@openmaic/renderer/snapshot', () => ({
  measureSlideElementGeometry: async () =>
    new Map([
      ['body', { x: 10, y: 10, w: 40, h: 30, centerX: 30, centerY: 25 }],
      ['answer', { x: 10, y: 50, w: 40, h: 20, centerX: 30, centerY: 60 }],
    ]),
  slideToPng: mocks.snapshot,
}));
vi.mock('@/lib/video-export-app/package-zip', () => ({ packageVideoZip: mocks.pack }));
import { buildTimelineProject } from '@/lib/classroom-video/timeline-project';

function plan(): ClassroomVideoPlan {
  return {
    renderer: 'openmaic-timeline-v1',
    stage: {
      id: 'c',
      name: '数组',
      coursewareTrial: { mode: 'learning-skills-enhanced', overview: '测试' },
    },
    scenes: [
      {
        id: 'p1',
        stageId: 'c',
        title: '数组',
        type: 'slide',
        order: 1,
        content: {
          type: 'slide',
          canvas: {
            id: 'canvas',
            elements: [
              {
                id: 'body',
                type: 'text',
                content: '数组定义',
                left: 100,
                top: 50,
                width: 400,
                height: 100,
              },
              {
                id: 'answer',
                type: 'text',
                content: '占四十字节',
                left: 100,
                top: 300,
                width: 400,
                height: 100,
              },
            ],
          },
        },
        actions: [
          { id: 's1', type: 'speech', text: '先看数组。' },
          { id: 'r1', type: 'reveal', elementId: 'answer', duration: 500, effect: 'fade-up' },
          { id: 's2', type: 'speech', text: '现在出现结论。' },
        ],
      },
    ],
    clips: [
      {
        sceneId: 'p1',
        key: 'a'.repeat(64),
        audio: { s1: { file: 'a.wav', sha256: 'a' }, s2: { file: 'b.wav', sha256: 'b' } },
      },
    ],
  } as unknown as ClassroomVideoPlan;
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal('document', { fonts: { ready: Promise.resolve() } });
  mocks.snapshot.mockResolvedValue(new Blob(['png']));
  mocks.pack.mockResolvedValue(new Blob(['zip']));
});
describe('AI trial deterministic video project', () => {
  it('compiles exact audio timing and hides the answer until its reveal', async () => {
    const result = await buildTimelineProject(
      plan(),
      'p1',
      { s1: 2, s2: 3 },
      { s1: 'YQ==', s2: 'Yg==' },
    );
    expect(result.duration).toBeCloseTo(5.5);
    expect(result.speech).toEqual([
      { actionId: 's1', offset: 0, duration: 2 },
      { actionId: 's2', offset: 2.5, duration: 3 },
    ]);
    expect(mocks.snapshot.mock.calls[0][0].elements.map((el: { id: string }) => el.id)).toEqual([
      'body',
    ]);
    expect(mocks.snapshot.mock.calls[1][0].elements.map((el: { id: string }) => el.id)).toEqual([
      'answer',
    ]);
    expect(mocks.snapshot.mock.calls[1][1].backgroundColor).toBe('transparent');
    const [project, blobs] = mocks.pack.mock.calls[0];
    const html = project.files.find((file: { path: string }) => file.path === 'index.html').content;
    expect(html).toContain('reveal-0-0');
    // A producer probes future frames before capture. Seeking back must hide the answer again.
    expect(html).toContain('tl.set("#reveal-0-0", {autoAlpha:0,y:0,scale:1}, 0)');
    expect(blobs.has('reveals/layer-0.png')).toBe(true);
  });
  it('rejects native and regular modes instead of silently recording through a different path', async () => {
    const snapshot = plan();
    snapshot.stage.coursewareTrial!.mode = 'faithful';
    await expect(buildTimelineProject(snapshot, 'p1', {}, {})).rejects.toThrow('未启用');
  });
  it('refuses missing audio or an unsupported action', async () => {
    await expect(buildTimelineProject(plan(), 'p1', { s1: 2 }, { s1: 'YQ==' })).rejects.toThrow(
      '配音',
    );
    const snapshot = plan();
    snapshot.scenes[0].actions!.push({ id: 'w', type: 'wb_open' });
    await expect(
      buildTimelineProject(snapshot, 'p1', { s1: 2, s2: 3 }, { s1: 'YQ==', s2: 'Yg==' }),
    ).rejects.toThrow('暂不支持');
  });
});
