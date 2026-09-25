/**
 * Platform navigation adaptation (see PLATFORM-INTEGRATION.md).
 *
 * Product-level "back to platform" targets for the teacher service overview
 * pages. In the same-domain deployment, use the browser's current origin so
 * production navigation never depends on a build-time development address.
 * A configured origin remains available outside the browser.
 *
 * Inlined at build time for production builds: rebuild after changing the
 * environment variable. Pages INSIDE a course workspace keep their own
 * internal navigation and intentionally do not use these helpers.
 */

export function platformOrigin(): string {
  if (typeof window !== 'undefined') return window.location.origin;
  return process.env.NEXT_PUBLIC_SAAS_HOST_ORIGIN?.trim() || '';
}

/** Teacher product portal — the product-level back target for overview pages. */
export function platformHomeUrl(): string {
  return `${platformOrigin().replace(/\/+$/, '')}/teacher`;
}

/** Platform student management page. */
export function platformStudentsUrl(): string {
  return `${platformOrigin()}/students`;
}

/** Platform learning-data page. */
export function platformLearningDataUrl(): string {
  return `${platformOrigin()}/learning-data`;
}
