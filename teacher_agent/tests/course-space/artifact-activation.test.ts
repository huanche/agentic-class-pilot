import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

const storage = vi.hoisted(() => ({
  readServerCourse: vi.fn(),
  readCourseArtifact: vi.fn(),
  saveCourseArtifact: vi.fn(),
  saveCourseArtifactFile: vi.fn(),
  updateCourseJobIfPresent: vi.fn(),
}));
vi.mock('@/lib/server/course-space-storage', () => storage);
import { PATCH } from '@/app/api/course-space/[courseId]/artifacts/[artifactId]/route';

/** Attached courseware artifacts carry a synthetic `attached_*` jobId with no job record. */
const attachedArtifact = {
  id: 'artifact-1',
  jobId: 'attached_nojob',
  courseId: 'course-a',
  teacherId: 'teacher-001',
  scope: { type: 'course' },
  type: 'lesson-courseware',
  title: 'Attached courseware',
  status: 'review',
  content: 'attached',
  citations: [],
};

const context = { params: Promise.resolve({ courseId: 'course-a', artifactId: 'artifact-1' }) };

function patchRequest(body: unknown): NextRequest {
  return new NextRequest('http://localhost/api/course-space/course-a/artifacts/artifact-1', {
    method: 'PATCH',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
}

describe('artifact activation', () => {
  beforeEach(() => vi.resetAllMocks());

  it('activates an attached courseware artifact that has no job record', async () => {
    storage.readServerCourse.mockResolvedValue({ id: 'course-a', status: 'active' });
    storage.readCourseArtifact.mockResolvedValue(attachedArtifact);
    storage.updateCourseJobIfPresent.mockResolvedValue(null);
    storage.saveCourseArtifact.mockImplementation(async (artifact) => artifact);

    const response = await PATCH(patchRequest({ action: 'activate' }), context);
    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body.artifact.status).toBe('published');
    expect(body.artifact.classPublicationId).toMatch(/^CLS-A-/);
    expect(storage.updateCourseJobIfPresent).toHaveBeenCalledWith(
      'attached_nojob',
      expect.objectContaining({ status: 'approved' }),
    );
  });

  it('keeps activation idempotent when a publication id already exists', async () => {
    storage.readServerCourse.mockResolvedValue({ id: 'course-a', status: 'active' });
    storage.readCourseArtifact.mockResolvedValue({ ...attachedArtifact, classPublicationId: 'CLS-A-existing' });

    const response = await PATCH(patchRequest({ action: 'activate' }), context);
    expect(response.status).toBe(200);
    expect((await response.json()).artifact.classPublicationId).toBe('CLS-A-existing');
    expect(storage.saveCourseArtifact).not.toHaveBeenCalled();
  });

  it('rejects deactivation after publication', async () => {
    storage.readServerCourse.mockResolvedValue({ id: 'course-a', status: 'active' });
    storage.readCourseArtifact.mockResolvedValue(attachedArtifact);

    const response = await PATCH(patchRequest({ action: 'deactivate' }), context);
    expect(response.status).toBe(409);
  });

  it('requires the course to be published before artifact activation', async () => {
    storage.readServerCourse.mockResolvedValue({ id: 'course-a', status: 'draft' });
    storage.readCourseArtifact.mockResolvedValue(attachedArtifact);

    const response = await PATCH(patchRequest({ action: 'activate' }), context);
    expect(response.status).toBe(409);
  });
});
