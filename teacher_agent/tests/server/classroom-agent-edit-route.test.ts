import { NextRequest } from 'next/server';
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  edit: vi.fn(),
  binding: vi.fn(),
  course: vi.fn(),
  classroom: vi.fn(),
}));
vi.mock('@/lib/server/agent-edit', () => ({ handleAgentEdit: mocks.edit }));
vi.mock('@/lib/server/course-space-database', () => ({
  readClassroomBindingFromDatabase: mocks.binding,
}));
vi.mock('@/lib/server/course-space-storage', () => ({ readServerCourse: mocks.course }));
vi.mock('@/lib/server/classroom-storage', () => ({
  isValidClassroomId: (id: string) => /^[\w-]+$/.test(id),
  readClassroom: mocks.classroom,
}));
import { POST } from '@/app/api/classroom/agent-edit/route';
import { POST as legacyPOST } from '@/app/api/agent/edit/route';

const body = () => ({
  message: '内容丰富点',
  scene: { id: 's2', title: '为什么要学C语言' },
  sceneContextMap: { s2: { stageId: 'class-1', content: { edited: '教师未保存的内容' } } },
});
const request = (payload: unknown = body(), user = 'teacher-1', query = '?id=class-1') =>
  new NextRequest(`http://localhost/api/classroom/agent-edit${query}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'x-platform-user-id': user },
    body: JSON.stringify(payload),
  });

describe('classroom-scoped page editing', () => {
  beforeEach(() => {
    vi.stubEnv('PLATFORM_AUTH_ENABLED', 'true');
    vi.stubEnv('NEXT_PUBLIC_MAIC_EDITOR_ENABLED', 'true');
    vi.resetAllMocks();
    mocks.binding.mockResolvedValue({ courseId: 'course-1' });
    mocks.course.mockResolvedValue({ teacherId: 'teacher-1' });
    mocks.classroom.mockResolvedValue({ scenes: [{ id: 's1' }, { id: 's2' }] });
    mocks.edit.mockResolvedValue(
      new Response('data: {}\n\n', { headers: { 'content-type': 'text/event-stream' } }),
    );
  });
  afterEach(() => vi.unstubAllEnvs());

  it('lets a non-admin owner edit the selected page and keeps the current canvas context', async () => {
    const req = request();
    const res = await POST(req);
    expect(res.status).toBe(200);
    expect(res.headers.get('content-type')).toBe('text/event-stream');
    expect(mocks.edit).toHaveBeenCalledWith(req, body());
  });
  it('rejects another teacher before a model call', async () => {
    expect((await POST(request(body(), 'teacher-2'))).status).toBe(403);
    expect(mocks.edit).not.toHaveBeenCalled();
  });
  it('rejects classrooms without a course binding in platform mode', async () => {
    mocks.binding.mockResolvedValue(null);
    expect((await POST(request())).status).toBe(404);
    expect(mocks.edit).not.toHaveBeenCalled();
  });
  it.each(['', '?id=../other'])('requires a valid ownership scope: %s', async (query) => {
    expect((await POST(request(body(), 'teacher-1', query))).status).toBe(400);
    expect(mocks.edit).not.toHaveBeenCalled();
  });
  it('rejects a context borrowed from another classroom even with a valid owned query', async () => {
    const payload = body();
    payload.sceneContextMap.s2.stageId = 'another-class';
    expect((await POST(request(payload))).status).toBe(400);
    expect(mocks.edit).not.toHaveBeenCalled();
  });
  it('rejects an unknown scene and extra contexts for other classrooms', async () => {
    for (const payload of [
      { ...body(), scene: { id: 'foreign-scene' } },
      {
        ...body(),
        sceneContextMap: { ...body().sceneContextMap, foreign: { stageId: 'class-1' } },
      },
      { ...body(), sceneContextMap: [] },
      null,
    ])
      expect((await POST(request(payload))).status).toBe(400);
    expect(mocks.edit).not.toHaveBeenCalled();
  });
  it('does not require a platform course binding in standalone local mode', async () => {
    vi.stubEnv('PLATFORM_AUTH_ENABLED', 'false');
    expect((await POST(request())).status).toBe(200);
    expect(mocks.binding).not.toHaveBeenCalled();
  });
  it('keeps the legacy transport wrapper from interpreting Next route context as an edit body', async () => {
    const req = request();
    await legacyPOST(req);
    expect(mocks.edit).toHaveBeenCalledWith(req);
  });
});
