import { NextRequest, NextResponse } from 'next/server';
import type { TeacherOperationPlan } from '@/lib/course-space/teacher-agent-intent';
import { executeConfirmedTeacherPlan } from '@/lib/server/teacher-course-operations';

export const runtime = 'nodejs';
export const maxDuration = 180;

export async function POST(request: NextRequest, context: { params: Promise<{ courseId: string }> }) {
  try {
    const { courseId } = await context.params;
    const body = await request.json() as { plan?: TeacherOperationPlan };
    if (!body.plan?.id || !body.plan.action) return NextResponse.json({ success: false, error: '无效的操作计划' }, { status: 400 });
    const result = await executeConfirmedTeacherPlan(courseId, body.plan);
    return NextResponse.json({ success: true, ...result });
  } catch (error) {
    return NextResponse.json({ success: false, error: error instanceof Error ? error.message : String(error) }, { status: 400 });
  }
}
