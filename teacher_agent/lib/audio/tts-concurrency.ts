/** Independent narration clips share a small pool; operators can select 1 for serial providers. */
export function ttsConcurrency(value: unknown): number {
  if (value === undefined || value === null || value === '') return 2;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.max(1, Math.min(4, Math.floor(parsed))) : 2;
}
