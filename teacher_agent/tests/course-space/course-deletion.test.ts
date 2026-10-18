import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';
import type { CourseArtifactJob } from '@/lib/course-space/types';

let directory = '';
beforeEach(async () => {
  directory = await mkdtemp(path.join(tmpdir(), 'course-delete-test-'));
  vi.stubEnv('COURSE_SPACES_DATA_DIR', directory);
  vi.stubEnv('COURSE_DATABASE_URL', '');
  vi.stubEnv('DATABASE_URL', '');
  vi.stubEnv('PLATFORM_AUTH_ENABLED', 'false');
  vi.resetModules();
});
afterEach(async () => {
  vi.unstubAllEnvs();
  if (
    path.dirname(directory) === path.resolve(tmpdir()) &&
    path.basename(directory).startsWith('course-delete-test-')
  )
    await rm(directory, { recursive: true, force: true });
});

describe('course deletion', () => {
  it('removes only the selected course from reads and retains bytes without allowing stale resurrection', async () => {
    const storage = await import('@/lib/server/course-space-storage');
    const course = await storage.createServerCourse({
      id: 'delete-me',
      teacherId: 'teacher-a',
      title: '待删除课程',
    });
    const keep = await storage.createServerCourse({ teacherId: 'teacher-a', title: '保留课程' });
    const material = await storage.storeCourseMaterial({
      courseId: course.id,
      teacherId: course.teacherId,
      fileName: 'source.txt',
      mimeType: 'text/plain',
      bytes: Buffer.from('original source'),
    });
    const stale = (await storage.readServerCourse(course.id))!;
    await storage.deleteServerCourse(course.id);
    expect(await storage.readServerCourse(course.id)).toBeNull();
    expect((await storage.listServerCourses(course.teacherId)).map((item) => item.id)).toEqual([
      keep.id,
    ]);
    expect(
      await readFile(path.join(directory, 'materials', material.id, 'source.txt'), 'utf8'),
    ).toBe('original source');
    await expect(storage.saveServerCourse(stale)).rejects.toThrow('课程已删除');
    await expect(storage.updateServerCourse(course.id, (value) => value)).rejects.toThrow(
      'Course not found',
    );
    await expect(
      storage.createServerCourse({
        id: course.id,
        teacherId: course.teacherId,
        title: 'stale retry',
      }),
    ).rejects.toThrow('课程标识已存在');
    await expect(storage.deleteServerCourse(course.id)).resolves.toBeUndefined();
  });

  it('serializes deletion with a save already in flight', async () => {
    const storage = await import('@/lib/server/course-space-storage');
    const course = await storage.createServerCourse({
      teacherId: 'teacher-a',
      title: 'Concurrent',
    });
    let entered!: () => void;
    let release!: () => void;
    const insideUpdate = new Promise<void>((resolve) => {
      entered = resolve;
    });
    const finishUpdate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const updating = storage.updateServerCourse(course.id, async (value) => {
      entered();
      await finishUpdate;
      return { ...value, title: 'Saved' };
    });
    await insideUpdate;
    const deleting = storage.deleteServerCourse(course.id);
    release();
    await Promise.all([updating, deleting]);
    expect(await storage.readServerCourse(course.id)).toBeNull();
  });

  it('returns a conflict for active jobs and permits deletion after they finish', async () => {
    const storage = await import('@/lib/server/course-space-storage');
    const course = await storage.createServerCourse({
      teacherId: 'teacher-a',
      title: 'Generating',
    });
    const job = {
      id: 'job-active',
      courseId: course.id,
      status: 'running',
      updatedAt: Date.now(),
      createdAt: Date.now(),
    } as CourseArtifactJob;
    await storage.saveCourseJob(job);
    const { DELETE } = await import('@/app/api/course-space/[courseId]/route');
    const request = new NextRequest(`http://localhost/api/course-space/${course.id}`, {
      method: 'DELETE',
    });
    const context = { params: Promise.resolve({ courseId: course.id }) };
    expect((await DELETE(request, context)).status).toBe(409);
    expect(await storage.readServerCourse(course.id)).not.toBeNull();
    await storage.saveCourseJob({ ...job, status: 'review' });
    expect((await DELETE(request, context)).status).toBe(200);
    expect(await storage.readServerCourse(course.id)).toBeNull();
  });

  it('blocks deletion while source parsing is active', async () => {
    const storage = await import('@/lib/server/course-space-storage');
    const course = await storage.createServerCourse({ teacherId: 'teacher-a', title: 'Parsing' });
    const material = await storage.storeCourseMaterial({
      courseId: course.id,
      teacherId: course.teacherId,
      fileName: 'source.txt',
      mimeType: 'text/plain',
      bytes: Buffer.from('original'),
    });
    await storage.updateServerCourse(course.id, (value) => ({
      ...value,
      materials: [{ ...material, status: 'parsing' }],
    }));
    await expect(storage.deleteServerCourse(course.id)).rejects.toThrow('解析任务');
    expect(await storage.readServerCourse(course.id)).not.toBeNull();
  });
});
