import type { NextRequest } from 'next/server';
import { handleAgentEdit } from '@/lib/server/agent-edit';
import { isMaicEditorEnabled } from '@/lib/config/feature-flags';

export const maxDuration = 300;
export async function POST(req: NextRequest) {
  if (!isMaicEditorEnabled()) return new Response('Not found', { status: 404 });
  return handleAgentEdit(req);
}
