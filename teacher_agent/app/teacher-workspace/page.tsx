/**
 * Stable SaaS integration entry for the teacher workspace.
 *
 * The existing /course-space route remains the canonical implementation during
 * the incremental split. Re-exporting it here gives the host a durable URL
 * without duplicating state or changing the current teacher experience.
 */
export { default } from '../course-space/page';
