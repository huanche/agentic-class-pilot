import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';
const mocks = vi.hoisted(() => ({ read: vi.fn(), retry: vi.fn(), run: vi.fn(), after: vi.fn() }));
vi.mock('next/server', async (original) => ({
  ...(await original<typeof import('next/server')>()),
  after: mocks.after,
}));
vi.mock('@/lib/server/course-space-storage', () => ({
  readCourseJob: mocks.read,
  isStaleActiveJob: () => false,
  updateCourseJob: vi.fn(),
}));
vi.mock('@/lib/server/background-courseware', () => ({
  retryBackgroundCoursewareJob: mocks.retry,
  runBackgroundCoursewareJob: mocks.run,
}));
import { PATCH } from '@/app/api/course-space/jobs/[jobId]/route';
const context = { params: Promise.resolve({ jobId: 'cw_retry' }) };
function request(owner: string) {
  return new NextRequest('http://localhost/api/course-space/jobs/cw_retry', {
    method: 'PATCH',
    headers: { 'content-type': 'application/json', 'x-platform-user-id': owner },
    body: JSON.stringify({ action: 'retry' }),
  });
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.stubEnv('PLATFORM_AUTH_ENABLED', 'true');
  mocks.read.mockResolvedValue({
    id: 'cw_retry',
    teacherId: 'owner',
    status: 'failed',
    backgroundGeneration: { classroomId: 'class' },
  });
  mocks.retry.mockResolvedValue({ id: 'cw_retry', status: 'queued' });
});
afterEach(() => vi.unstubAllEnvs());
describe('explicit courseware retry', () => {
  it('authorizes before restarting a task or scheduling provider calls', async () => {
    expect((await PATCH(request('another-teacher'), context)).status).toBe(403);
    expect(mocks.retry).not.toHaveBeenCalled();
    expect(mocks.after).not.toHaveBeenCalled();
  });
  it('queues the owner request and starts the worker after the response', async () => {
    const response = await PATCH(request('owner'), context);
    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject({ done: false, job: { status: 'queued' } });
    expect(mocks.retry).toHaveBeenCalledWith('cw_retry');
    expect(mocks.run).not.toHaveBeenCalled();
    await mocks.after.mock.calls[0][0]();
    expect(mocks.run).toHaveBeenCalledWith('cw_retry');
  });
  it('does not schedule work when the original input is gone', async () => {
    mocks.retry.mockRejectedValue(new Error('原生成计划已不存在'));
    expect((await PATCH(request('owner'), context)).status).toBe(400);
    expect(mocks.after).not.toHaveBeenCalled();
  });
});
