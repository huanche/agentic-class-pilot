export function courseWorkspaceUrl(courseId: string): string {
  return `/course-space?workspace=${encodeURIComponent(courseId)}`;
}

/** Use an explicit application parent, never an unrelated browser-history entry. */
export function teacherReturnUrl(
  from: string | null | undefined,
  fallback = '/course-space',
): string {
  if (!from || !from.startsWith('/') || from.startsWith('//') || /[\\\u0000-\u0020]/.test(from))
    return fallback;
  try {
    const url = new URL(from, 'https://teacher.invalid');
    if (url.origin !== 'https://teacher.invalid') return fallback;
    if (!/^\/(course-space|teacher-workspace|classes)(\/|$)/.test(url.pathname)) return fallback;
    // Preview → review → preview must not turn the Back button into a loop.
    if (/\/(review|artifacts\/[^/]+\/view)(\/|$)/.test(url.pathname)) return fallback;
    return `${url.pathname}${url.search}${url.hash}`;
  } catch {
    return fallback;
  }
}

export function withTeacherReturn(url: string, from: string): string {
  const parsed = new URL(url, 'https://teacher.invalid');
  parsed.searchParams.set('from', teacherReturnUrl(from));
  return parsed.origin === 'https://teacher.invalid'
    ? `${parsed.pathname}${parsed.search}${parsed.hash}`
    : parsed.toString();
}
