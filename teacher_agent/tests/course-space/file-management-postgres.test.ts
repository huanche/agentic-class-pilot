import { randomUUID } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { Client } from 'pg';
import { NextRequest } from 'next/server';
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import type {
  CourseArtifactRecord,
  CourseMaterialRecord,
  CourseSpace,
} from '@/lib/course-space/types';

// Opt in explicitly. Neither DATABASE_URL nor a developer's .env can select the test database.
const testUrl = process.env.TEST_COURSE_DATABASE_URL;
const integration = testUrl ? describe : describe.skip;
const schema = `acceptance_pg_${randomUUID().replaceAll('-', '')}`;
let admin: Client;
let directory = '';
let storage: typeof import('@/lib/server/course-space-storage');
let database: typeof import('@/lib/server/course-space-database');
let management: typeof import('@/app/api/course-space/[courseId]/management/route');
let materialRoute: typeof import('@/app/api/course-space/[courseId]/materials/[materialId]/route');
let artifactRoute: typeof import('@/app/api/course-space/[courseId]/artifacts/[artifactId]/route');
let fileRoute: typeof import('@/app/api/course-space/[courseId]/lesson-files/[fileId]/route');
let extractionRoute: typeof import('@/app/api/course-space/[courseId]/materials/[materialId]/extraction/route');
let courseRoute: typeof import('@/app/api/course-space/[courseId]/route');
let course: CourseSpace;
let original: CourseMaterialRecord;
let artifact: CourseArtifactRecord;
let packageId: string;

const request = (body: unknown) =>
  new NextRequest('http://localhost/api/test', {
    method: 'PATCH',
    body: JSON.stringify(body),
  });
const metadata = (body: unknown) =>
  management.PATCH(request(body), {
    params: Promise.resolve({ courseId: course.id }),
  });
const materialContext = () => ({
  params: Promise.resolve({ courseId: course.id, materialId: original.id }),
});
const fileContext = () => ({
  params: Promise.resolve({ courseId: course.id, fileId: `${course.id}-file` }),
});
const artifactContext = () => ({
  params: Promise.resolve({ courseId: course.id, artifactId: artifact.id }),
});
async function replace(text = 'replacement bytes — 中文') {
  const form = new FormData();
  form.set('file', new File([text], 'new-source.txt', { type: 'text/plain' }));
  return materialRoute.PUT(
    new NextRequest('http://localhost/api/material', { method: 'PUT', body: form }),
    materialContext(),
  );
}
async function freshSnapshot() {
  const inputPath = path.join(directory, `${course.id}.json`);
  await writeFile(
    inputPath,
    JSON.stringify({ courseId: course.id, artifactId: artifact.id, original, packageId }),
  );
  const child = spawnSync(
    process.execPath,
    ['tests/course-space/helpers/read-postgres-snapshot.mjs', inputPath],
    {
      cwd: process.cwd(),
      env: { ...process.env },
      encoding: 'utf8',
      timeout: 30000,
    },
  );
  expect(child.error, child.stderr).toBeUndefined();
  expect(child.status, child.stderr).toBe(0);
  return JSON.parse(child.stdout);
}

integration('real PostgreSQL course file management (no storage or route mocks)', () => {
  beforeAll(async () => {
    const url = new URL(testUrl!);
    if (
      !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname) ||
      !/^\/course_file_acceptance_[a-z0-9_]+$/.test(url.pathname)
    ) {
      throw new Error('Use a loopback PostgreSQL database named course_file_acceptance_<suffix>');
    }
    directory = await mkdtemp(path.join(tmpdir(), 'course-pg-acceptance-'));
    admin = new Client({ connectionString: testUrl });
    await admin.connect();
    await admin.query(`CREATE SCHEMA ${schema}`);
    vi.stubEnv('COURSE_STORAGE_MODE', 'postgres');
    vi.stubEnv('COURSE_DATABASE_URL', testUrl!);
    vi.stubEnv('DATABASE_URL', '');
    vi.stubEnv('COURSE_DATABASE_SCHEMA', schema);
    vi.stubEnv('COURSE_DATABASE_MANAGE_SCHEMA', 'true');
    vi.stubEnv('COURSE_SPACES_DATA_DIR', path.join(directory, 'unused-json-fallback'));
    vi.stubEnv('COURSE_OBJECT_STORAGE_MODE', 'database');
    vi.stubEnv('PLATFORM_AUTH_ENABLED', 'false');
    vi.resetModules();
    try {
      storage = await import('@/lib/server/course-space-storage');
      database = await import('@/lib/server/course-space-database');
      management = await import('@/app/api/course-space/[courseId]/management/route');
      materialRoute =
        await import('@/app/api/course-space/[courseId]/materials/[materialId]/route');
      artifactRoute =
        await import('@/app/api/course-space/[courseId]/artifacts/[artifactId]/route');
      fileRoute = await import('@/app/api/course-space/[courseId]/lesson-files/[fileId]/route');
      extractionRoute =
        await import('@/app/api/course-space/[courseId]/materials/[materialId]/extraction/route');
      courseRoute = await import('@/app/api/course-space/[courseId]/route');
      expect(await database.getCourseDatabaseHealth()).toMatchObject({
        configured: true,
        connected: true,
      });
    } catch (error) {
      console.error(
        'PostgreSQL acceptance setup failed:',
        error instanceof Error ? error.stack : error,
      );
      throw error;
    }
  }, 30000);

  beforeEach(async () => {
    const id = `pg-${randomUUID()}`;
    course = await storage.createServerCourse({
      id,
      teacherId: 'acceptance-teacher',
      title: '隔离课程',
    });
    original = await storage.storeCourseMaterial({
      courseId: id,
      teacherId: course.teacherId,
      purpose: 'course-outline',
      fileName: 'original.txt',
      mimeType: 'text/plain',
      bytes: Buffer.from('original bytes — 中文'),
    });
    original = { ...original, status: 'ready' };
    const placement = {
      lessonId: `${id}-lesson`,
      week: 1,
      lessonNumber: 1,
      teachingHours: 2,
      resourceType: 'knowledge-points' as const,
      confirmedAt: 123,
    };
    course = await storage.updateServerCourse(id, (current) => ({
      ...current,
      status: 'active',
      materials: current.materials.map((item) => (item.id === original.id ? original : item)),
      modules: [
        {
          id: `${id}-module`,
          courseId: id,
          title: '第一周',
          order: 1,
          objectives: [],
          createdAt: 1,
          updatedAt: 1,
          lessons: [
            {
              id: `${id}-lesson`,
              moduleId: `${id}-module`,
              title: '第一课',
              order: 1,
              objectives: [],
              materialIds: [original.id],
              createdAt: 1,
              updatedAt: 1,
              files: [
                {
                  id: `${id}-file`,
                  lessonId: `${id}-lesson`,
                  type: 'knowledge-points',
                  title: '已发布文件',
                  content: '原始正文',
                  status: 'ready',
                  classPublicationId: 'CLS-file',
                  classVisible: true,
                  classPublishedAt: 123,
                  publicationPlacement: placement,
                  createdAt: 1,
                  updatedAt: 1,
                },
              ],
            },
            {
              id: `${id}-lesson-two`,
              moduleId: `${id}-module`,
              title: '第二课',
              order: 2,
              objectives: [],
              materialIds: [original.id],
              createdAt: 1,
              updatedAt: 1,
            },
          ],
        },
      ],
    }));
    artifact = await storage.saveCourseArtifact({
      id: `${id}-artifact`,
      jobId: `${id}-job`,
      teacherId: course.teacherId,
      courseId: id,
      scope: { type: 'lesson', lessonId: `${id}-lesson` },
      type: 'lesson-courseware',
      title: '已发布课件',
      content: '课件正文',
      sourceMaterialId: original.id,
      citations: [
        { materialId: original.id, sourceName: original.name, sourceSha256: original.sha256! },
      ],
      status: 'published',
      classVisible: true,
      classPublicationId: 'CLS-artifact',
      classPublishedAt: 123,
      publicationPlacement: { ...placement, resourceType: 'courseware' },
      createdAt: 1,
      updatedAt: 1,
    });
    packageId = `${id}-knowledge`;
    await storage.saveKnowledgePackage({
      id: packageId,
      teacherId: course.teacherId,
      courseId: id,
      version: 1,
      status: 'published',
      entries: [
        {
          id: `${id}-entry`,
          courseId: id,
          title: '历史知识',
          content: '历史内容',
          approvedAt: 123,
          citations: artifact.citations,
        },
      ],
      createdAt: 1,
      publishedAt: 123,
    });
    await storage.saveMaterialExtraction({
      materialId: original.id,
      courseId: id,
      sourceSha256: original.sha256!,
      parser: 'acceptance',
      text: 'original bytes — 中文',
      pageCount: 1,
      formulas: [],
      chunks: [],
      createdAt: 123,
    });
  });

  afterAll(async () => {
    await database?.getCourseDatabasePool()?.end();
    if (admin) {
      // Only the random schema created by this suite is removed; the caller's database stays intact.
      await admin.query(`DROP SCHEMA IF EXISTS ${schema} CASCADE`);
      await admin.end();
    }
    vi.unstubAllEnvs();
    if (
      path.dirname(directory) === path.resolve(tmpdir()) &&
      path.basename(directory).startsWith('course-pg-acceptance-')
    )
      await rm(directory, { recursive: true, force: true });
  });

  it.each(['artifacts', 'materials', 'lesson-files', 'modules', 'lessons'] as const)(
    'persists rename/pin/unpin for %s across fresh processes while preserving all other fields',
    async (kind) => {
      if (kind === 'materials') {
        course = await storage.updateServerCourse(course.id, (current) => ({
          ...current,
          materials: current.materials.map((item) => ({
            ...item,
            classVisible: true,
            classPublicationId: 'CLS-material',
            classPublishedAt: 123,
          })),
        }));
      }
      const id =
        kind === 'artifacts'
          ? artifact.id
          : kind === 'materials'
            ? original.id
            : kind === 'lesson-files'
              ? `${course.id}-file`
              : kind === 'modules'
                ? `${course.id}-module`
                : `${course.id}-lesson`;
      const entity = (snapshot: Awaited<ReturnType<typeof freshSnapshot>>) =>
        kind === 'artifacts'
          ? snapshot.artifact
          : kind === 'materials'
            ? snapshot.course.materials[0]
            : kind === 'lesson-files'
              ? snapshot.course.modules[0].lessons[0].files[0]
              : kind === 'modules'
                ? snapshot.course.modules[0]
                : snapshot.course.modules[0].lessons[0];
      const before = entity(await freshSnapshot());
      expect((await metadata({ kind, id, title: '  新名称  ', pinned: true })).status).toBe(200);
      const renamed = entity(await freshSnapshot());
      expect(renamed).toEqual({
        ...before,
        [kind === 'materials' ? 'name' : 'title']: kind === 'materials' ? '新名称.txt' : '新名称',
        pinned: true,
        updatedAt: expect.any(Number),
      });
      expect((await metadata({ kind, id, pinned: false })).status).toBe(200);
      expect(entity(await freshSnapshot())).toEqual({
        ...renamed,
        pinned: false,
        updatedAt: expect.any(Number),
      });
    },
    30000,
  );

  it('persists text saves and approvals, preserves references, and rejects edits of published resources', async () => {
    expect(
      (
        await artifactRoute.PATCH(
          request({ action: 'save', content: 'unsafe published edit' }),
          artifactContext(),
        )
      ).status,
    ).toBe(409);
    expect(
      (
        await fileRoute.PATCH(
          request({ action: 'save', content: 'unsafe published edit' }),
          fileContext(),
        )
      ).status,
    ).toBe(409);
    expect(
      (await artifactRoute.PATCH(request({ action: 'deactivate' }), artifactContext())).status,
    ).toBe(200);
    expect((await fileRoute.PATCH(request({ action: 'unpublish' }), fileContext())).status).toBe(
      200,
    );
    expect(
      (
        await artifactRoute.PATCH(
          request({ action: 'save', content: '  新文本课件  ' }),
          artifactContext(),
        )
      ).status,
    ).toBe(200);
    expect(
      (await fileRoute.PATCH(request({ action: 'save', content: '  新知识点  ' }), fileContext()))
        .status,
    ).toBe(200);
    let restored = await freshSnapshot();
    expect(restored.artifact).toMatchObject({
      content: '新文本课件',
      status: 'review',
      sourceMaterialId: original.id,
      citations: artifact.citations,
    });
    expect(restored.course.modules[0].lessons[0].files[0]).toMatchObject({
      content: '新知识点',
      status: 'draft',
      lessonId: `${course.id}-lesson`,
    });
    expect(
      (await artifactRoute.PATCH(request({ action: 'approve' }), artifactContext())).status,
    ).toBe(200);
    expect(
      (await fileRoute.PATCH(request({ action: 'approve', content: '新知识点' }), fileContext()))
        .status,
    ).toBe(200);
    restored = await freshSnapshot();
    expect(restored.artifact.status).toBe('approved');
    expect(restored.course.modules[0].lessons[0].files[0].status).toBe('ready');
    const mirror = await database
      .getCourseDatabasePool()!
      .query('SELECT title,status,content,payload FROM mentra_course_lesson_files WHERE id=$1', [
        `${course.id}-file`,
      ]);
    expect(mirror.rows[0]).toMatchObject({
      title: '已发布文件',
      status: 'ready',
      content: '新知识点',
      payload: restored.course.modules[0].lessons[0].files[0],
    });
  }, 30000);

  it('retains both changes when two requests rename and pin the same artifact concurrently', async () => {
    const responses = await Promise.all([
      metadata({ kind: 'artifacts', id: artifact.id, title: '并发重命名' }),
      metadata({ kind: 'artifacts', id: artifact.id, pinned: true }),
    ]);
    expect(responses.map((response) => response.status)).toEqual([200, 200]);
    const restored = await freshSnapshot();
    expect(restored.artifact).toMatchObject({ title: '并发重命名', pinned: true });
  }, 30000);

  it('downloads and replaces real bytea files, updates all active locations, and retains historical citations and bytes after a fresh process starts', async () => {
    const downloaded = await materialRoute.GET(
      new NextRequest('http://localhost/api/material'),
      materialContext(),
    );
    expect(downloaded.status).toBe(200);
    expect(Buffer.from(await downloaded.arrayBuffer())).toEqual(
      Buffer.from('original bytes — 中文'),
    );
    expect(downloaded.headers.get('content-disposition')).toContain('original.txt');
    expect((await metadata({ kind: 'materials', id: original.id, pinned: true })).status).toBe(200);
    const response = await replace();
    expect(response.status).toBe(200);
    const { material } = await response.json();
    expect(material).toMatchObject({
      name: 'new-source.txt',
      pinned: true,
      status: 'uploaded',
      purpose: 'course-outline',
    });
    expect(material.id).not.toBe(original.id);
    expect(material.sha256).not.toBe(original.sha256);
    const restored = await freshSnapshot();
    expect(restored.course.materials).toEqual([material]);
    expect(
      restored.course.modules[0].lessons.map(
        (lesson: { materialIds: string[] }) => lesson.materialIds,
      ),
    ).toEqual([[material.id], [material.id]]);
    expect(restored.artifact).toEqual(artifact);
    expect(restored.knowledgePackage.entries[0].citations).toEqual(artifact.citations);
    expect(restored.extraction).toMatchObject({
      materialId: original.id,
      sourceSha256: original.sha256,
    });
    expect(restored.originalBytes).toBe(Buffer.from('original bytes — 中文').toString('base64'));
    expect(restored.currentBytes).toBe(Buffer.from('replacement bytes — 中文').toString('base64'));
    const historicalDownload = await materialRoute.GET(
      new NextRequest('http://localhost/api/material'),
      materialContext(),
    );
    expect(historicalDownload.status).toBe(200);
    expect(await historicalDownload.text()).toBe('original bytes — 中文');
    const historicalExtraction = await extractionRoute.GET(
      new NextRequest('http://localhost/api/extraction'),
      materialContext(),
    );
    expect(historicalExtraction.status).toBe(200);
    expect((await historicalExtraction.json()).extraction).toEqual(restored.extraction);
    const currentDownload = await materialRoute.GET(
      new NextRequest('http://localhost/api/material'),
      { params: Promise.resolve({ courseId: course.id, materialId: material.id }) },
    );
    expect(await currentDownload.text()).toBe('replacement bytes — 中文');
    const rows = await database
      .getCourseDatabasePool()!
      .query('SELECT material_id,bytes FROM mentra_course_material_files WHERE course_id=$1', [
        course.id,
      ]);
    expect(rows.rows).toHaveLength(2);
    expect(rows.rows.find((row) => row.material_id === original.id)?.bytes).toEqual(
      Buffer.from('original bytes — 中文'),
    );
  }, 30000);

  it('protects archived versions from stale full-course saves and preserves server-owned history in PostgreSQL', async () => {
    const stale = (await storage.readServerCourse(course.id))!;
    const replaced = await replace();
    expect(replaced.status).toBe(200);
    const { material } = await replaced.json();
    const current = (await storage.readServerCourse(course.id))!;
    const save = (body: CourseSpace) =>
      courseRoute.PUT(
        new NextRequest('http://localhost/api/course', {
          method: 'PUT',
          body: JSON.stringify(body),
        }),
        { params: Promise.resolve({ courseId: course.id }) },
      );
    expect((await save({ ...current, materials: stale.materials })).status).toBe(409);
    expect((await save({ ...current, modules: stale.modules })).status).toBe(409);
    expect((await save({ ...current, archivedMaterials: [] })).status).toBe(200);
    const restored = await freshSnapshot();
    expect(restored.course.materials).toEqual([{ ...material, classVisible: false }]);
    expect(restored.course.archivedMaterials).toEqual([original]);
    const originalDownload = await materialRoute.GET(
      new NextRequest('http://localhost/api/material'),
      materialContext(),
    );
    expect(originalDownload.status).toBe(200);
    expect(await originalDownload.text()).toBe('original bytes — 中文');
    const foreign = await storage.createServerCourse({
      teacherId: 'foreign-teacher',
      title: '隔离其他课程',
    });
    const foreignContext = {
      params: Promise.resolve({ courseId: foreign.id, materialId: original.id }),
    };
    expect(
      (await materialRoute.GET(new NextRequest('http://localhost/api/material'), foreignContext))
        .status,
    ).toBe(404);
    expect(
      (
        await extractionRoute.GET(
          new NextRequest('http://localhost/api/extraction'),
          foreignContext,
        )
      ).status,
    ).toBe(404);
  }, 30000);

  it.each(['published', 'parsing'] as const)(
    'rejects replacement while %s without changing durable records',
    async (state) => {
      await storage.updateServerCourse(course.id, (current) => ({
        ...current,
        materials: current.materials.map((item) => ({
          ...item,
          ...(state === 'published'
            ? { classPublicationId: 'CLS-material', classVisible: true }
            : { status: 'parsing' as const }),
        })),
      }));
      const before = await freshSnapshot();
      expect((await replace()).status).toBe(409);
      expect(await freshSnapshot()).toEqual(before);
    },
    30000,
  );
});
