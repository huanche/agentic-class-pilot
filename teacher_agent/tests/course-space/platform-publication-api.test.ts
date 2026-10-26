import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

const storage = vi.hoisted(() => ({
  readServerCourse: vi.fn(),
  readPublishedKnowledgePackage: vi.fn(),
}));
vi.mock('@/lib/server/course-space-storage', () => storage);

import { GET } from '@/app/api/internal/platform/courses/[courseId]/publication/route';

const context = { params: Promise.resolve({ courseId: 'legacy-course-id' }) };
const request = (delegated = true) => new NextRequest(
  'http://localhost/api/internal/platform/courses/legacy-course-id/publication',
  { headers: delegated ? { 'x-platform-delegated': 'true' } : {} },
);

beforeEach(() => {
  vi.resetAllMocks();
  vi.stubEnv('PLATFORM_AUTH_ENABLED', 'true');
  storage.readServerCourse.mockResolvedValue({ id: 'canonical-id', status: 'active' });
  storage.readPublishedKnowledgePackage.mockResolvedValue({
    id: 'package-id', status: 'published', version: 3,
  });
});

describe('platform publication verdict', () => {
  it('requires middleware-confirmed platform delegation', async () => {
    expect((await GET(request(false), context)).status).toBe(403);
    expect(storage.readServerCourse).not.toHaveBeenCalled();
    vi.stubEnv('PLATFORM_AUTH_ENABLED', 'false');
    expect((await GET(request(), context)).status).toBe(403);
    expect(storage.readServerCourse).not.toHaveBeenCalled();
  });

  it('resolves a legacy alias and returns the current publication identity', async () => {
    const response = await GET(request(), context);
    expect(await response.json()).toEqual({
      published: true,
      publication: { publicationId: 'package-id', version: 3 },
    });
    expect(storage.readPublishedKnowledgePackage).toHaveBeenCalledWith('canonical-id');
  });

  it('rejects an inactive course or withdrawn package', async () => {
    storage.readServerCourse.mockResolvedValueOnce({ id: 'canonical-id', status: 'draft' });
    expect(await (await GET(request(), context)).json()).toEqual({ published: false, publication: null });
    storage.readPublishedKnowledgePackage.mockResolvedValueOnce(null);
    expect(await (await GET(request(), context)).json()).toEqual({ published: false, publication: null });
  });
});
