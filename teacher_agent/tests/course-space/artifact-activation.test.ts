import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

const storage = vi.hoisted(() => ({
  readServerCourse: vi.fn(),
  readCourseArtifact: vi.fn(),
  readCourseJob: vi.fn(),
  saveCourseArtifact: vi.fn(),
  saveCourseArtifactFile: vi.fn(),
  updateCourseJobIfPresent: vi.fn(),
  updateServerCourse: vi.fn(),
  deleteCourseArtifact: vi.fn(),
  listCourseArtifacts: vi.fn(),
  listKnowledgePackages: vi.fn(),
  saveKnowledgePackage: vi.fn(),
}));
vi.mock('@/lib/server/course-space-storage', () => storage);
import { PATCH, DELETE } from '@/app/api/course-space/[courseId]/artifacts/[artifactId]/route';

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
const course = {
  id: 'course-a',
  status: 'active',
  materials: [],
  modules: [{ id: 'module-a', lessons: [{ id: 'lesson-a', materialIds: [], files: [] }] }],
};
const placement = {
  lessonId: 'lesson-a',
  week: 1,
  lessonNumber: 1,
  teachingHours: 2,
  resourceType: 'courseware',
};

function patchRequest(body: unknown): NextRequest {
  return new NextRequest('http://localhost/api/course-space/course-a/artifacts/artifact-1', {
    method: 'PATCH',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ placement, ...(body as object) }),
  });
}

describe('artifact activation', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    storage.updateServerCourse.mockImplementation(async (_id, update) =>
      update(structuredClone(course)),
    );
    storage.saveCourseArtifact.mockImplementation(async (artifact) => artifact);
    storage.readCourseJob.mockResolvedValue(null);
    storage.listCourseArtifacts.mockResolvedValue([]);
    storage.listKnowledgePackages.mockResolvedValue([]);
    storage.saveKnowledgePackage.mockImplementation(async (pkg) => pkg);
  });

  it('activates an attached courseware artifact that has no job record', async () => {
    storage.readServerCourse.mockResolvedValue(course);
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
    storage.readServerCourse.mockResolvedValue(course);
    storage.readCourseArtifact.mockResolvedValue({
      ...attachedArtifact,
      classPublicationId: 'CLS-A-existing',
      publicationPlacement: placement,
    });

    const response = await PATCH(patchRequest({ action: 'activate' }), context);
    expect(response.status).toBe(200);
    expect((await response.json()).artifact.classPublicationId).toBe('CLS-A-existing');
    expect(storage.saveCourseArtifact).not.toHaveBeenCalled();
  });

  it('withdraws a publication and clears its confirmed lesson binding', async () => {
    storage.readServerCourse.mockResolvedValue(course);
    storage.readCourseArtifact.mockResolvedValue({
      ...attachedArtifact,
      status: 'published',
      classVisible: true,
      classPublicationId: 'CLS-A-existing',
      publicationPlacement: placement,
    });

    const response = await PATCH(patchRequest({ action: 'deactivate' }), context);
    expect(response.status).toBe(200);
    expect((await response.json()).artifact).toMatchObject({
      status: 'approved',
      classVisible: false,
    });
    expect(storage.saveCourseArtifact.mock.calls[0][0].classPublicationId).toBeUndefined();
    expect(storage.saveCourseArtifact.mock.calls[0][0].publicationPlacement).toBeUndefined();
  });

  it('automatically enables student publication when confirming draft courseware', async () => {
    const draft = { ...structuredClone(course), status: 'draft' };
    storage.readServerCourse.mockResolvedValue(draft);
    storage.updateServerCourse.mockImplementation(async (_id, update) =>
      Object.assign(draft, update(draft)),
    );
    storage.readCourseArtifact.mockResolvedValue(attachedArtifact);

    const response = await PATCH(patchRequest({ action: 'activate' }), context);
    expect(response.status).toBe(200);
    expect((await response.json()).artifact.status).toBe('published');
    expect(draft.status).toBe('active');
    expect(storage.saveKnowledgePackage).toHaveBeenCalledTimes(1);
  });
  it('deletes only resources owned by the canonical course', async () => {
    storage.readServerCourse.mockResolvedValue(course);
    storage.readCourseArtifact.mockResolvedValue(attachedArtifact);
    expect((await DELETE(patchRequest({}), context)).status).toBe(200);
    expect(storage.deleteCourseArtifact).toHaveBeenCalledWith('artifact-1');
    storage.deleteCourseArtifact.mockClear();
    storage.readCourseArtifact.mockResolvedValue({ ...attachedArtifact, courseId: 'foreign' });
    expect((await DELETE(patchRequest({}), context)).status).toBe(404);
    expect(storage.deleteCourseArtifact).not.toHaveBeenCalled();
  });
});
