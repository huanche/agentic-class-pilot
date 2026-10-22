/** Classroom ownership is resolved by the platform from this query parameter. */
export function agentEditEndpoint(stageId: string | undefined): string {
  return stageId
    ? `/api/classroom/agent-edit?id=${encodeURIComponent(stageId)}`
    : '/api/agent/edit';
}

export async function agentEditError(response: Response): Promise<string> {
  const fallback = `修改本页失败（${response.status}），请稍后重试`;
  const body = await response.json().catch(() => null);
  return typeof body?.error === 'string' && body.error.trim() ? body.error : fallback;
}
