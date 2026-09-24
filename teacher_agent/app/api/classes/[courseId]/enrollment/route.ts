import { NextRequest } from 'next/server';
import { platformEnrollmentCode } from '@/lib/server/platform-enrollment';

export async function GET(request: NextRequest, context: { params: Promise<{ courseId: string }> }) {
  return platformEnrollmentCode(request, (await context.params).courseId);
}
