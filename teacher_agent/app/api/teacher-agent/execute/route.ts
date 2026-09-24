import { type NextRequest } from 'next/server';
import { apiError, apiSuccess } from '@/lib/server/api-response';
import type { TeacherOperationPlan } from '@/lib/course-space/teacher-agent-intent';
import { executeConfirmedTeacherPlan } from '@/lib/server/teacher-course-operations';

export const runtime = 'nodejs';
export const maxDuration = 180;

export async function POST(request: NextRequest) {
  try {
    const body = await request.json() as { courseId?: string; plan?: TeacherOperationPlan };
    const courseId = body.courseId?.trim();
    if (!courseId || !body.plan?.id || !body.plan.action) {
      return apiError('MISSING_REQUIRED_FIELD', 400, '缺少 courseId 或有效操作计划');
    }
    if (body.plan.status !== 'planned') return apiError('INVALID_REQUEST', 409, '操作计划已执行或不可执行');
    const result = await executeConfirmedTeacherPlan(courseId, body.plan);
    return apiSuccess(result);
  } catch (error) {
    return apiError('INVALID_REQUEST', 400, error instanceof Error ? error.message : String(error));
  }
}
