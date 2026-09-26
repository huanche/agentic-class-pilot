import { mkdtemp, rm } from 'fs/promises';
import { tmpdir } from 'os';
import path from 'path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { CourseArtifactJob } from '@/lib/course-space/types';

let testDir = '';

function makeJob(overrides: Partial<CourseArtifactJob>): CourseArtifactJob {
  const now = Date.now();
  return {
    id: 'job-test',
    teacherId: 'teacher-a',
    courseId: 'course-a',
    scope: { type: 'course' },
    artifactType: 'lesson-courseware',
    status: 'running',
    progress: 50,
    message: 'generating',
    createdAt: now - 60_000,
    updatedAt: now - 60_000,
    ...overrides,
  };
}

beforeEach(async () => {
  testDir = await mkdtemp(path.join(tmpdir(), 'stale-job-sweep-'));
  process.env.COURSE_SPACES_DATA_DIR = testDir;
  vi.resetModules();
});

afterEach(async () => {
  delete process.env.COURSE_SPACES_DATA_DIR;
  if (testDir) await rm(testDir, { recursive: true, force: true });
});

describe('stale artifact job sweep', () => {
  it('marks only long-silent queued/running jobs failed', async () => {
    const storage = await import('@/lib/server/course-space-storage');
    const now = Date.now();
    const staleRunning = makeJob({ id: 'stale-running', updatedAt: now - 20 * 60 * 1000 });
    const staleQueued = makeJob({
      id: 'stale-queued',
      status: 'queued',
      progress: 0,
      updatedAt: now - 20 * 60 * 1000,
    });
    const freshRunning = makeJob({ id: 'fresh-running', updatedAt: now - 60_000 });
    const staleApproved = makeJob({
      id: 'stale-approved',
      status: 'approved',
      progress: 100,
      updatedAt: now - 20 * 60 * 1000,
    });
    await Promise.all(
      [staleRunning, staleQueued, freshRunning, staleApproved].map((job) => storage.saveCourseJob(job)),
    );

    const swept = await storage.sweepStaleCourseJobs('course-a');

    expect(new Set(swept.map((job) => job.id))).toEqual(new Set(['stale-running', 'stale-queued']));
    expect((await storage.readCourseJob('stale-running'))?.status).toBe('failed');
    expect((await storage.readCourseJob('stale-running'))?.message).toBe('生成进程已中断，可重新创建任务');
    expect((await storage.readCourseJob('stale-queued'))?.status).toBe('failed');
    expect((await storage.readCourseJob('fresh-running'))?.status).toBe('running');
    expect((await storage.readCourseJob('stale-approved'))?.status).toBe('approved');
  });

  it('sweeps every course at once for the startup pass', async () => {
    const storage = await import('@/lib/server/course-space-storage');
    const now = Date.now();
    await storage.saveCourseJob(
      makeJob({ id: 'zombie-other-course', courseId: 'course-b', updatedAt: now - 20 * 60 * 1000 }),
    );
    await storage.saveCourseJob(makeJob({ id: 'live-job', updatedAt: now - 60_000 }));

    const swept = await storage.sweepAllStaleCourseJobs();

    expect(swept.map((job) => job.id)).toEqual(['zombie-other-course']);
    expect((await storage.readCourseJob('zombie-other-course'))?.status).toBe('failed');
    expect((await storage.readCourseJob('live-job'))?.status).toBe('running');
  });

  it('detects staleness per job record', async () => {
    const { isStaleActiveJob, STALE_ACTIVE_JOB_MS } = await import(
      '@/lib/server/course-space-storage'
    );
    const now = Date.now();
    expect(isStaleActiveJob(makeJob({ updatedAt: now - STALE_ACTIVE_JOB_MS - 1 }), now)).toBe(true);
    expect(isStaleActiveJob(makeJob({ updatedAt: now - STALE_ACTIVE_JOB_MS + 1 }), now)).toBe(false);
    expect(
      isStaleActiveJob(makeJob({ status: 'failed', updatedAt: now - STALE_ACTIVE_JOB_MS - 1 }), now),
    ).toBe(false);
  });
});
