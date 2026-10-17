import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { NextRequest } from 'next/server';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

let directory = '';
let storage: typeof import('@/lib/server/course-space-storage');
let materials: typeof import('@/app/api/course-space/[courseId]/materials/[materialId]/route');
let extractions: typeof import('@/app/api/course-space/[courseId]/materials/[materialId]/extraction/route');
let courseId: string;
let original: Awaited<ReturnType<typeof storage.storeCourseMaterial>>;

const context = (materialId: string, requestedCourseId = courseId) => ({
  params: Promise.resolve({ courseId: requestedCourseId, materialId }),
});

async function replace(materialId: string, text: string, fileName: string) {
  const form = new FormData();
  form.set('file', new File([text], fileName, { type: 'text/plain' }));
  const response = await materials.PUT(
    new NextRequest('http://localhost/api/material', { method: 'PUT', body: form }),
    context(materialId),
  );
  expect(response.status).toBe(200);
  return (await response.json()).material as typeof original;
}

const download = (materialId: string, requestedCourseId = courseId) =>
  materials.GET(
    new NextRequest('http://localhost/api/material'),
    context(materialId, requestedCourseId),
  );

beforeEach(async () => {
  directory = await mkdtemp(path.join(tmpdir(), 'course-material-history-'));
  vi.stubEnv('COURSE_SPACES_DATA_DIR', directory);
  vi.stubEnv('COURSE_STORAGE_MODE', 'json');
  vi.stubEnv('COURSE_DATABASE_URL', '');
  vi.stubEnv('DATABASE_URL', '');
  vi.stubEnv('COURSE_OBJECT_STORAGE_MODE', 'database');
  vi.stubEnv('PLATFORM_AUTH_ENABLED', 'false');
  vi.resetModules();
  storage = await import('@/lib/server/course-space-storage');
  materials = await import('@/app/api/course-space/[courseId]/materials/[materialId]/route');
  extractions =
    await import('@/app/api/course-space/[courseId]/materials/[materialId]/extraction/route');
  const course = await storage.createServerCourse({
    teacherId: 'history-teacher',
    title: '历史引用验收',
  });
  courseId = course.id;
  original = await storage.storeCourseMaterial({
    courseId,
    teacherId: course.teacherId,
    fileName: 'original.txt',
    mimeType: 'text/plain',
    bytes: Buffer.from('original source bytes'),
  });
  await storage.saveMaterialExtraction({
    materialId: original.id,
    courseId,
    sourceSha256: original.sha256!,
    text: 'original extracted text',
    pageCount: 1,
    chunks: [
      { id: 'history-chunk', materialId: original.id, page: 1, text: 'original extracted text' },
    ],
    formulas: [],
    createdAt: Date.now(),
  });
  original = { ...original, status: 'ready' };
  await storage.updateServerCourse(courseId, (current) => ({
    ...current,
    materials: current.materials.map((item) => (item.id === original.id ? original : item)),
    modules: [
      {
        id: 'history-module',
        courseId,
        title: 'History module',
        order: 1,
        objectives: [],
        createdAt: 1,
        updatedAt: 1,
        lessons: [
          {
            id: 'history-lesson',
            moduleId: 'history-module',
            title: 'History lesson',
            order: 1,
            objectives: [],
            materialIds: [original.id],
            createdAt: 1,
            updatedAt: 1,
          },
        ],
      },
    ],
  }));
  await storage.saveCourseArtifact({
    id: 'history-artifact',
    jobId: 'attached_history',
    teacherId: course.teacherId,
    courseId,
    scope: { type: 'course' },
    type: 'narration',
    title: '引用旧源文件的产物',
    content: `Source [material:${original.id} page:1]`,
    status: 'approved',
    sourceMaterialId: original.id,
    citations: [
      {
        materialId: original.id,
        sourceName: original.name,
        sourceSha256: original.sha256!,
        page: 1,
      },
    ],
    createdAt: Date.now(),
    updatedAt: Date.now(),
  });
});

afterEach(async () => {
  vi.unstubAllEnvs();
  if (
    path.dirname(directory) === path.resolve(tmpdir()) &&
    path.basename(directory).startsWith('course-material-history-')
  )
    await rm(directory, { recursive: true, force: true });
});

describe('source material history through real routes', () => {
  it('keeps each cited source downloadable after repeated replacements and module reload', async () => {
    const second = await replace(original.id, 'second source bytes', 'second.txt');
    const third = await replace(second.id, 'third source bytes', 'third.txt');
    expect((await storage.readServerCourse(courseId))?.materials.map((item) => item.id)).toEqual([
      third.id,
    ]);

    // Reload the storage and routes to prove history is durable, not an in-memory cache.
    vi.resetModules();
    storage = await import('@/lib/server/course-space-storage');
    materials = await import('@/app/api/course-space/[courseId]/materials/[materialId]/route');
    for (const [record, expected] of [
      [original, 'original source bytes'],
      [second, 'second source bytes'],
      [third, 'third source bytes'],
    ] as const) {
      const response = await download(record.id);
      expect(response.status, `download material ${record.name}`).toBe(200);
      expect(await response.text()).toBe(expected);
      expect(response.headers.get('content-disposition')).toContain(
        encodeURIComponent(record.name),
      );
    }
    const artifact = await storage.readCourseArtifact('history-artifact');
    expect(artifact?.sourceMaterialId).toBe(original.id);
    expect(artifact?.citations[0]).toMatchObject({
      materialId: original.id,
      sourceSha256: original.sha256,
    });
  });

  it('keeps the extraction used by an existing citation readable after source replacement', async () => {
    await replace(original.id, 'new source bytes', 'new.txt');
    const response = await extractions.GET(
      new NextRequest('http://localhost/api/extraction'),
      context(original.id),
    );
    expect(response.status).toBe(200);
    const result = await response.json();
    expect(result.extraction).toMatchObject({
      materialId: original.id,
      sourceSha256: original.sha256,
      text: 'original extracted text',
    });
  });

  it('does not expose another course source through the historical download or extraction route', async () => {
    await replace(original.id, 'new source bytes', 'new.txt');
    const otherCourse = await storage.createServerCourse({
      teacherId: 'other-teacher',
      title: 'Other course',
    });
    expect((await download(original.id, otherCourse.id)).status).toBe(404);
    expect(
      (
        await extractions.GET(
          new NextRequest('http://localhost/api/extraction'),
          context(original.id, otherCourse.id),
        )
      ).status,
    ).toBe(404);
    expect((await download('missing-material')).status).toBe(404);
  });

  it('preserves server-owned history when a full course save omits or replaces it', async () => {
    const latest = await replace(original.id, 'new source bytes', 'new.txt');
    const courseRoute = await import('@/app/api/course-space/[courseId]/route');
    const current = (await storage.readServerCourse(courseId))!;
    for (const archivedMaterials of [undefined, []]) {
      const response = await courseRoute.PUT(
        new NextRequest('http://localhost/api/course', {
          method: 'PUT',
          body: JSON.stringify({ ...current, archivedMaterials }),
        }),
        { params: Promise.resolve({ courseId }) },
      );
      expect(response.status).toBe(200);
      expect((await download(original.id)).status).toBe(200);
      expect((await storage.readServerCourse(courseId))?.materials.map((item) => item.id)).toEqual([
        latest.id,
      ]);
    }
  });

  it('keeps archived versions read-only for replacement and parsing', async () => {
    const latest = await replace(original.id, 'new source bytes', 'new.txt');
    const form = new FormData();
    form.set(
      'file',
      new File(['must not replace history'], 'history-edit.txt', { type: 'text/plain' }),
    );
    expect(
      (
        await materials.PUT(
          new NextRequest('http://localhost/api/material', { method: 'PUT', body: form }),
          context(original.id),
        )
      ).status,
    ).toBe(404);
    const parseRoute =
      await import('@/app/api/course-space/[courseId]/materials/[materialId]/parse/route');
    expect(
      (
        await parseRoute.POST(
          new NextRequest('http://localhost/api/parse', { method: 'POST' }),
          context(original.id),
        )
      ).status,
    ).toBe(404);
    expect((await storage.readServerCourse(courseId))?.materials.map((item) => item.id)).toEqual([
      latest.id,
    ]);
  });

  it('rejects a structural save overtaken by replacement while its request body is arriving', async () => {
    const stale = (await storage.readServerCourse(courseId))!;
    const courseRoute = await import('@/app/api/course-space/[courseId]/route');
    let bodyRequested!: () => void;
    const reading = new Promise<void>((resolve) => (bodyRequested = resolve));
    let sendBody!: () => void;
    const released = new Promise<void>((resolve) => (sendBody = resolve));
    const body = new ReadableStream<Uint8Array>(
      {
        async pull(controller) {
          bodyRequested();
          await released;
          controller.enqueue(new TextEncoder().encode(JSON.stringify(stale)));
          controller.close();
        },
      },
      { highWaterMark: 0 },
    );
    const pending = courseRoute.PUT(
      new NextRequest('http://localhost/api/course', { method: 'PUT', body }),
      { params: Promise.resolve({ courseId }) },
    );
    await reading;
    const latest = await replace(original.id, 'new source bytes', 'new.txt');
    sendBody();
    expect((await pending).status).toBe(409);
    expect((await storage.readServerCourse(courseId))?.materials[0].id).toBe(latest.id);
    expect(await (await download(original.id)).text()).toBe('original source bytes');
  });

  it.each(['materials', 'lesson references'])(
    'rejects a stale full-course save that restores archived %s',
    async (field) => {
      const stale = (await storage.readServerCourse(courseId))!;
      const latest = await replace(original.id, 'new source bytes', 'new.txt');
      const current = (await storage.readServerCourse(courseId))!;
      const body =
        field === 'materials'
          ? { ...current, materials: stale.materials }
          : { ...current, modules: stale.modules };
      const courseRoute = await import('@/app/api/course-space/[courseId]/route');
      const response = await courseRoute.PUT(
        new NextRequest('http://localhost/api/course', {
          method: 'PUT',
          body: JSON.stringify(body),
        }),
        { params: Promise.resolve({ courseId }) },
      );
      expect(response.status).toBe(409);
      const restored = (await storage.readServerCourse(courseId))!;
      expect(restored.materials.map((item) => item.id)).toEqual([latest.id]);
      expect(restored.modules[0].lessons[0].materialIds).toEqual([latest.id]);
      expect((await download(original.id)).status).toBe(200);
    },
  );
});
