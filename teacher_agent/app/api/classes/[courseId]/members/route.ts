import { type NextRequest } from 'next/server';
import { platformCourseMembersResponse } from '@/lib/server/platform-course-members';

export async function GET(request: NextRequest, context: { params: Promise<{ courseId: string }> }) {
  return platformCourseMembersResponse(request, (await context.params).courseId);
}
