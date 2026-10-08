import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

const mocks = vi.hoisted(() => ({
  readServerCourse: vi.fn(),
  planTeacherWorkspaceOperation: vi.fn(),
  executeReadOnlyTeacherPlan: vi.fn(),
  runTeacherWorkspaceAgent: vi.fn(),
  getPlatformUserModelConfigForRequest: vi.fn(),
  beginTeacherTurn: vi.fn(),
  completeTeacherTurn: vi.fn(),
  failTeacherTurn: vi.fn(),
}));
vi.mock('@/lib/server/course-space-storage', () => ({ readServerCourse: mocks.readServerCourse }));
vi.mock('@/lib/course-space/teacher-agent-intent', () => ({
  planTeacherWorkspaceOperation: mocks.planTeacherWorkspaceOperation,
}));
vi.mock('@/lib/server/teacher-course-operations', () => ({
  executeReadOnlyTeacherPlan: mocks.executeReadOnlyTeacherPlan,
}));
vi.mock('@/lib/server/teacher-workspace-agent', () => ({
  runTeacherWorkspaceAgent: mocks.runTeacherWorkspaceAgent,
}));
vi.mock('@/lib/server/course-space-storage-adapter', () => ({
  getCourseSpaceStorageAdapter: () => ({
    beginTeacherTurn: mocks.beginTeacherTurn,
    completeTeacherTurn: mocks.completeTeacherTurn,
    failTeacherTurn: mocks.failTeacherTurn,
  }),
}));
vi.mock('@/lib/server/platform-user-model-config', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/server/platform-user-model-config')>();
  return { ...actual, getPlatformUserModelConfigForRequest: mocks.getPlatformUserModelConfigForRequest };
});

import { POST } from '@/app/api/course-space/[courseId]/agent/route';

const context = { params: Promise.resolve({ courseId: 'course-a' }) };
const lease = { sessionId: 'teacher-course-a-default', token: 'mock-lease' };
const headers = {
  'content-type': 'application/json',
  'x-model': 'openai/browser-model',
  'x-api-key': 'browser-key',
  'x-base-url': 'https://browser.example/v1',
  'x-provider-type': 'openai',
};
function request(body: Record<string, unknown> = {}, requestHeaders = headers) {
  return new NextRequest('http://localhost/api/course-space/course-a/agent', {
    method: 'POST', headers: requestHeaders,
    body: JSON.stringify({ message: '解释知识点', ...body }),
  });
}

describe('teacher agent route', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mocks.readServerCourse.mockResolvedValue({
      id: 'course-a', teacherId: 'teacher-a', title: '课程 A', modules: [], materials: [],
    });
    mocks.beginTeacherTurn.mockResolvedValue(lease);
    mocks.getPlatformUserModelConfigForRequest.mockResolvedValue(null);
    mocks.runTeacherWorkspaceAgent.mockResolvedValue({ text: '回答', mode: 'deepseek-compatible' });
  });

  it('returns confirmation plans without executing them or calling the chat agent', async () => {
    const plan = {
      id: 'plan-a', status: 'planned', requiresConfirmation: true,
      action: { type: 'create-lesson-files', populateContent: true, lessonIds: ['l1', 'l2'] },
    };
    mocks.planTeacherWorkspaceOperation.mockReturnValue(plan);
    const response = await POST(request(), context);
    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject({ success: true, plan, mode: 'course-operator' });
    expect(mocks.executeReadOnlyTeacherPlan).not.toHaveBeenCalled();
    expect(mocks.runTeacherWorkspaceAgent).not.toHaveBeenCalled();
    expect(mocks.getPlatformUserModelConfigForRequest).not.toHaveBeenCalled();
    expect(mocks.completeTeacherTurn).toHaveBeenCalledWith(lease, expect.objectContaining({ plan }));
  });

  it('preserves read-only planner execution', async () => {
    const plan = { id: 'inspect', requiresConfirmation: false, status: 'planned' };
    mocks.planTeacherWorkspaceOperation.mockReturnValue(plan);
    mocks.executeReadOnlyTeacherPlan.mockResolvedValue({ ...plan, status: 'completed', result: '检查结果' });
    const response = await POST(request(), context);
    expect(response.status).toBe(200);
    expect(mocks.executeReadOnlyTeacherPlan).toHaveBeenCalledWith('course-a', plan);
    expect(mocks.runTeacherWorkspaceAgent).not.toHaveBeenCalled();
  });

  it('passes model headers, thinking and bounded web context but ignores body platform overrides', async () => {
    const thinkingConfig = { effort: 'high' };
    await POST(request({
      thinkingConfig, webContext: 'W'.repeat(24000) + 'TOO_LONG',
      platformOverrides: { modelString: 'untrusted', apiKey: 'untrusted' },
      modelConfig: { platformOverrides: { modelString: 'untrusted', apiKey: 'untrusted' } },
    }), context);
    expect(mocks.runTeacherWorkspaceAgent).toHaveBeenCalledWith(expect.objectContaining({
      modelConfig: {
        modelString: headers['x-model'], apiKey: headers['x-api-key'],
        baseUrl: headers['x-base-url'], providerType: headers['x-provider-type'], thinkingConfig,
      },
      webContext: 'W'.repeat(24000),
    }));
  });

  it('uses only trusted platform BYOK and drops stale browser connection headers', async () => {
    const req = request({
      thinkingConfig: { effort: 'high' },
      modelConfig: { platformOverrides: { modelString: 'attacker', apiKey: 'attacker' } },
    });
    mocks.getPlatformUserModelConfigForRequest.mockResolvedValue({
      llm: { model: 'platform-model', apiKey: 'platform-key', baseUrl: 'https://platform.example/v1' },
    });
    const response = await POST(req, context);
    expect(response.status).toBe(200);
    expect(mocks.getPlatformUserModelConfigForRequest).toHaveBeenCalledWith(req);
    expect(mocks.runTeacherWorkspaceAgent.mock.calls[0]?.[0].modelConfig).toEqual({
      platformOverrides: {
        modelString: 'openai/platform-model', apiKey: 'platform-key', baseUrl: 'https://platform.example/v1',
      },
      thinkingConfig: { effort: 'high' },
    });
  });

  it('falls back to normal header/stage resolution when platform lookup returns null on failure', async () => {
    // The shared platform helper turns fetch/network failures into null.
    mocks.getPlatformUserModelConfigForRequest.mockResolvedValue(null);
    const response = await POST(request({ thinking: { enabled: true } }), context);
    expect(response.status).toBe(200);
    expect(mocks.runTeacherWorkspaceAgent.mock.calls[0]?.[0].modelConfig).toMatchObject({
      modelString: headers['x-model'], thinkingConfig: { enabled: true },
    });
    expect(mocks.runTeacherWorkspaceAgent.mock.calls[0]?.[0].modelConfig.platformOverrides).toBeUndefined();
  });

  it('falls back for incomplete platform model settings', async () => {
    mocks.getPlatformUserModelConfigForRequest.mockResolvedValue({ llm: { model: 'no-key' } });
    await POST(request(), context);
    expect(mocks.runTeacherWorkspaceAgent.mock.calls[0]?.[0].modelConfig.modelString).toBe(headers['x-model']);
    expect(mocks.runTeacherWorkspaceAgent.mock.calls[0]?.[0].modelConfig.platformOverrides).toBeUndefined();
  });

  it('records unexpected platform lookup exceptions as failed turns rather than hiding them', async () => {
    const error = new Error('unexpected lookup failure');
    mocks.getPlatformUserModelConfigForRequest.mockRejectedValue(error);
    const response = await POST(request(), context);
    expect(response.status).toBe(500);
    expect(await response.json()).toEqual({ success: false, error: error.message });
    expect(mocks.failTeacherTurn).toHaveBeenCalledWith(lease, error);
    expect(mocks.runTeacherWorkspaceAgent).not.toHaveBeenCalled();
    expect(mocks.completeTeacherTurn).not.toHaveBeenCalled();
  });

  it('does not forward non-string web context', async () => {
    await POST(request({ webContext: { instruction: 'untrusted' } }), context);
    expect(mocks.runTeacherWorkspaceAgent.mock.calls[0]?.[0].webContext).toBeUndefined();
  });
});