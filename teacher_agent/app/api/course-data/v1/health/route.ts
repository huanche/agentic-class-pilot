import { apiSuccess } from '@/lib/server/api-response';
import { getCourseDatabaseHealth } from '@/lib/server/course-space-database';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET() {
  return apiSuccess({ apiVersion: 'v1', database: await getCourseDatabaseHealth() });
}
