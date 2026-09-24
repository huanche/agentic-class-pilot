import { afterEach, describe, expect, it } from 'vitest';
import { NextRequest } from 'next/server';
import { authorizeStudentAgent } from '@/lib/server/student-agent-auth';

const previous = process.env.STUDENT_AGENT_API_KEY;

afterEach(() => {
  if (previous === undefined) delete process.env.STUDENT_AGENT_API_KEY;
  else process.env.STUDENT_AGENT_API_KEY = previous;
});

describe('student agent API authentication', () => {
  it('fails closed when the server key is absent', () => {
    delete process.env.STUDENT_AGENT_API_KEY;
    const response = authorizeStudentAgent(new NextRequest('http://localhost/api/student-agent/v1/courses/a'));
    expect(response?.status).toBe(503);
  });

  it('rejects an invalid bearer token', () => {
    process.env.STUDENT_AGENT_API_KEY = 'correct-token';
    const response = authorizeStudentAgent(new NextRequest('http://localhost/api/student-agent/v1/courses/a', {
      headers: { authorization: 'Bearer incorrect-token' },
    }));
    expect(response?.status).toBe(401);
  });

  it('accepts the configured bearer token', () => {
    process.env.STUDENT_AGENT_API_KEY = 'correct-token';
    const response = authorizeStudentAgent(new NextRequest('http://localhost/api/student-agent/v1/courses/a', {
      headers: { authorization: 'Bearer correct-token' },
    }));
    expect(response).toBeNull();
  });
});
