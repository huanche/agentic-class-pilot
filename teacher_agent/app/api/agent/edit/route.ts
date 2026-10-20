import type { NextRequest } from 'next/server';
import { handleAgentEdit } from '@/lib/server/agent-edit';

export const maxDuration = 300;
export async function POST(req: NextRequest) {
  return handleAgentEdit(req);
}
