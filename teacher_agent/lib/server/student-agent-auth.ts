import { timingSafeEqual } from 'node:crypto';
import type { NextRequest } from 'next/server';
import { apiError } from '@/lib/server/api-response';

export function authorizeStudentAgent(request: NextRequest) {
  const expected = process.env.STUDENT_AGENT_API_KEY?.trim();
  if (!expected) {
    return apiError('MISSING_API_KEY', 503, '学生智能体接口尚未配置服务端密钥');
  }
  const authorization = request.headers.get('authorization') ?? '';
  const supplied = authorization.startsWith('Bearer ') ? authorization.slice(7).trim() : '';
  const left = Buffer.from(expected);
  const right = Buffer.from(supplied);
  if (!supplied || left.length !== right.length || !timingSafeEqual(left, right)) {
    return apiError('INVALID_CREDENTIALS', 401, '学生智能体凭证无效');
  }
  return null;
}
