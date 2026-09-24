/**
 * Platform navigation adaptation (see PLATFORM-INTEGRATION.md).
 *
 * Product-level "back to platform" targets for the teacher service overview
 * pages. The origin comes exclusively from NEXT_PUBLIC_SAAS_HOST_ORIGIN
 * (set by the launchers: http://localhost:8080 locally, the site origin in
 * the same-domain /teacher reverse-proxy deployment). Business components
 * must not hardcode the platform host.
 *
 * Inlined at build time for production builds: rebuild after changing the
 * environment variable. Pages INSIDE a course workspace keep their own
 * internal navigation and intentionally do not use these helpers.
 */

export function platformOrigin(): string {
  return process.env.NEXT_PUBLIC_SAAS_HOST_ORIGIN || 'http://localhost:8080';
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
