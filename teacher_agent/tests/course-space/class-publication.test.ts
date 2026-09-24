import { beforeEach, describe, expect, it, vi } from 'vitest';

const storage = vi.hoisted(() => ({
  readServerCourse: vi.fn(),
  listCourseArtifacts: vi.fn(),
}));
vi.mock('@/lib/server/course-space-storage', () => storage);
import { GET } from '@/app/api/classes/[courseId]/route';

describe('Class publication boundary', () => {
  const context = { params: Promise.resolve({ courseId: 'course-a' }) };
  const request = new Request('http://localhost/api/classes/course-a');
  beforeEach(() => vi.resetAllMocks());

  it('does not expose a draft course', async () => {
    storage.readServerCourse.mockResolvedValue({ id: 'course-a', status: 'draft' });
    expect((await GET(request, context)).status).toBe(404);
  });

  it('only exposes explicitly published resources and clears lesson drafts', async () => {
    storage.readServerCourse.mockResolvedValue({
      id: 'course-a', title: 'Course', status: 'active',
      materials: [
        { id: 'private-material', name: 'Private', classVisible: true },
        { id: 'public-material', name: 'Public', classVisible: true, classPublicationId: 'CLS-M-1' },
      ],
      modules: [{ id: 'module-a', objectives: ['draft objective'], lessons: [{
        id: 'lesson-a', materialIds: ['private-material'], objectives: ['draft lesson'],
        files: [{ id: 'private-file', content: 'draft' }],
      }] }],
    });
    storage.listCourseArtifacts.mockResolvedValue([
      { id: 'draft', status: 'review', classVisible: true, classPublicationId: 'CLS-A-0' },
      { id: 'unconfirmed', status: 'published', classVisible: true },
      { id: 'confirmed', title: 'Published', status: 'published', classVisible: true, classPublicationId: 'CLS-A-1' },
    ]);
    const response = await GET(request, context);
    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body.resources.map((item: { id: string }) => item.id).sort()).toEqual(['confirmed', 'public-material']);
    expect(body.course.modules[0].objectives).toEqual([]);
    expect(body.course.modules[0].lessons[0].files).toEqual([]);
    expect(body.course.modules[0].lessons[0].materialIds).toEqual([]);
  });
});
