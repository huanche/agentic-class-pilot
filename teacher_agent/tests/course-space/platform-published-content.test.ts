import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

const storage = vi.hoisted(() => ({
  readServerCourse: vi.fn(),
  readPublishedKnowledgePackage: vi.fn(),
  listStoredCourseArtifacts: vi.fn(),
  readClassroom: vi.fn(),
}));
vi.mock('@/lib/server/course-space-storage', () => ({
  readServerCourse: storage.readServerCourse,
  readPublishedKnowledgePackage: storage.readPublishedKnowledgePackage,
  listStoredCourseArtifacts: storage.listStoredCourseArtifacts,
}));
vi.mock('@/lib/server/classroom-storage', () => ({ readClassroom: storage.readClassroom }));

import { GET } from '@/app/api/internal/platform/courses/[courseId]/published-content/route';

const context = { params: Promise.resolve({ courseId: 'platform-uuid' }) };
const request = (delegated = true) => new NextRequest(
  'http://localhost/api/internal/platform/courses/platform-uuid/published-content',
  { headers: delegated ? { 'x-platform-delegated': 'true' } : {} },
);

const activeCourse = (overrides: Record<string, unknown> = {}) => ({
  id: 'canonical-id', status: 'active',
  modules: [{ id: 'm1', lessons: [{ id: 'L1', title: '课时一', order: 1, week: 1, lessonNumber: 1, teachingHours: 2, files: [] }] }],
  materials: [],
  ...overrides,
});

beforeEach(() => {
  vi.resetAllMocks();
  vi.stubEnv('PLATFORM_AUTH_ENABLED', 'true');
  storage.readServerCourse.mockResolvedValue(activeCourse());
  storage.readPublishedKnowledgePackage.mockResolvedValue({ id: 'pkg-1', version: 3, status: 'published' });
  storage.listStoredCourseArtifacts.mockResolvedValue([]);
  storage.readClassroom.mockResolvedValue(null);
});

describe('platform published learning content', () => {
  it('requires authenticated service delegation', async () => {
    expect((await GET(request(false), context)).status).toBe(403);
    expect(storage.readServerCourse).not.toHaveBeenCalled();
  });

  it('returns no content for an inactive course', async () => {
    storage.readServerCourse.mockResolvedValue(activeCourse({ status: 'archived' }));
    expect(await (await GET(request(), context)).json()).toEqual({ published: false, content: null });
    expect(storage.readPublishedKnowledgePackage).not.toHaveBeenCalled();
  });

  it('returns no content when no knowledge package is published', async () => {
    storage.readPublishedKnowledgePackage.mockResolvedValue({ id: 'pkg-1', version: 3, status: 'superseded' });
    expect(await (await GET(request(), context)).json()).toEqual({ published: false, content: null });
  });

  it('collects visible artifacts, lesson files and materials in legacy order', async () => {
    storage.listStoredCourseArtifacts.mockResolvedValue([
      { id: 'a-old', title: '旧工件', content: '旧', status: 'published', classVisible: true,
        classPublicationId: 'p1', createdAt: 100, citations: [],
        publicationPlacement: { lessonId: 'L1', resourceType: 'courseware' } },
      { id: 'a-new', title: '新工件', content: '新', status: 'published', classVisible: true,
        classPublicationId: 'p2', createdAt: 200, citations: [{ source: 'x' }],
        publicationPlacement: { lessonId: 'L1', resourceType: 'objectives' } },
      { id: 'a-hidden', title: '未发布', content: '', status: 'published', classVisible: false,
        classPublicationId: 'p3', createdAt: 300, citations: [] },
      { id: 'a-draft', title: '未发布工件', content: '', status: 'approved', classVisible: true,
        classPublicationId: 'p4', createdAt: 400, citations: [] },
    ]);
    storage.readServerCourse.mockResolvedValue(activeCourse({
      modules: [{ id: 'm1', lessons: [{ id: 'L1', title: '课时一', order: 1, files: [
        { id: 'f1', title: '知识点文件', content: '# 知识', type: 'knowledge-points', classVisible: true, classPublicationId: 'pf1' },
        { id: 'f2', title: '隐藏文件', content: '', type: 'outline', classVisible: false, classPublicationId: 'pf2' },
      ] }] }],
      materials: [{ id: 'mat1', name: '资料', classVisible: true, classPublicationId: 'pm1', publicationPlacement: { lessonId: 'L1' } }],
    }));

    const body = await (await GET(request(), context)).json();
    expect(body.published).toBe(true);
    expect(body.content.publication).toEqual({ publicationId: 'pkg-1', version: 3 });
    expect(body.content.entries.map((entry: { id: string }) => entry.id))
      .toEqual(['a-old', 'a-new', 'f1', 'mat1']);
    const artifact = body.content.entries[1];
    expect(artifact).toMatchObject({ kind: 'artifact', resourceType: 'objectives',
      scope: { type: 'lesson', lessonId: 'L1' }, publicationId: 'p2' });
    expect(body.content.entries[2]).toMatchObject({ kind: 'lesson-file', resourceType: 'knowledge-points' });
    expect(body.content.entries[3]).toMatchObject({ kind: 'material',
      url: '/api/course-space/canonical-id/materials/mat1',
      scope: { type: 'lesson', lessonId: 'L1' } });
  });

  it('selects the newest published classroom per lesson and projects scenes', async () => {
    storage.listStoredCourseArtifacts.mockResolvedValue([
      { id: 'a2', title: '', content: '', status: 'published', classVisible: true,
        classPublicationId: 'p2', classroomId: 'room-2', classPublishedAt: 200, createdAt: 2,
        citations: [], publicationPlacement: { lessonId: 'L1', week: 1, lessonNumber: 1, teachingHours: 2 } },
      { id: 'a1', title: '', content: '', status: 'published', classVisible: true,
        classPublicationId: 'p1', classroomId: 'room-1', classPublishedAt: 100, createdAt: 1,
        citations: [], publicationPlacement: { lessonId: 'L1' } },
    ]);
    storage.readClassroom.mockResolvedValue({
      id: 'room-2', stage: { name: '课堂名' },
      scenes: [
        { id: 's2', type: 'slide', order: 2, title: '第二页',
          content: { canvas: { elements: [{ type: 'text', content: '<b>要点</b>&nbsp;二' }] } },
          actions: [{ id: 'act2', type: 'speech', text: '旁白二' }, 'invalid'] },
        { id: 's1', type: 'slide', order: 1, title: '第一页',
          content: { canvas: { elements: [{ type: 'text', content: '要点一' }] } }, actions: [] },
      ],
    });

    const body = await (await GET(request(), context)).json();
    expect(storage.readClassroom).toHaveBeenCalledWith('room-2');
    expect(body.content.lessons).toHaveLength(1);
    const lesson = body.content.lessons[0];
    expect(lesson).toMatchObject({ id: 'L1', title: '课时一', order: 1, week: 1,
      lessonNumber: 1, teachingHours: 2, publishedAt: 200 });
    expect(lesson.classroom).toMatchObject({ id: 'room-2', title: '课堂名' });
    expect(lesson.classroom.scenes.map((scene: { id: string }) => scene.id)).toEqual(['s1', 's2']);
    // `<b>要点</b>&nbsp;二` → tags become spaces, nbsp survives as U+00A0,
    // one entry per text element (mirrors Python unescape + strip).
    expect(lesson.classroom.scenes[1].visibleText).toEqual(['要点  二']);
    expect(lesson.classroom.scenes[1].actions).toEqual([{ id: 'act2', type: 'speech', text: '旁白二' }]);
  });

  it('fails with 404 when the selected lesson snapshot is missing', async () => {
    storage.listStoredCourseArtifacts.mockResolvedValue([
      { id: 'a1', title: '', content: '', status: 'published', classVisible: true,
        classPublicationId: 'p1', classroomId: 'room-missing', classPublishedAt: 100, createdAt: 1,
        citations: [], publicationPlacement: { lessonId: 'L1' } },
    ]);
    storage.readClassroom.mockResolvedValue(null);
    const response = await GET(request(), context);
    expect(response.status).toBe(404);
    expect((await response.json()).error).toBe('课堂不存在或尚未发布');
  });

  it('ignores artifacts whose lesson no longer exists in the course payload', async () => {
    storage.listStoredCourseArtifacts.mockResolvedValue([
      { id: 'a1', title: '', content: '', status: 'published', classVisible: true,
        classPublicationId: 'p1', classroomId: 'room-1', classPublishedAt: 100, createdAt: 1,
        citations: [], scope: { type: 'lesson', lessonId: 'deleted-lesson' } },
    ]);
    const body = await (await GET(request(), context)).json();
    expect(body.content.lessons).toEqual([]);
    expect(storage.readClassroom).not.toHaveBeenCalled();
  });
});
