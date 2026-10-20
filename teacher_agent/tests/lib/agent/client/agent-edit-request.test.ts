import { describe, expect, it } from 'vitest';
import { agentEditEndpoint, agentEditError } from '@/lib/agent/client/agent-edit-request';

describe('agent edit request', () => {
  it('routes saved classrooms through the ownership-scoped endpoint', () => {
    expect(agentEditEndpoint('class-1')).toBe('/api/classroom/agent-edit?id=class-1');
    expect(agentEditEndpoint(undefined)).toBe('/api/agent/edit');
  });
  it('shows the server rejection rather than a bare HTTP status', async () => {
    expect(
      await agentEditError(Response.json({ error: '无权修改此课程的课件' }, { status: 403 })),
    ).toBe('无权修改此课程的课件');
    expect(await agentEditError(new Response('gateway error', { status: 502 }))).toContain('502');
  });
});
