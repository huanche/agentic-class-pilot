import { randomUUID } from 'crypto';

import { nanoid } from 'nanoid';
import { type NextRequest } from 'next/server';

import { DEFAULT_TEACHER_ID, type CreateCourseSpaceInput } from '@/lib/course-space/types';

/**
 * Platform adaptation for course identity and registration.
 *
 * Together with lib/server/platform-auth.ts this file is the complete,
 * self-contained platform integration surface of the course-space creation
 * route. When a new upstream teacher-agent revision is merged, re-port by
 * copying these two modules and re-applying the minimal hooks listed in
 * docs/platform-integration-porting.md — no other business file encodes
 * platform semantics.
 */

export function isPlatformAuthEnabled(): boolean {
  return process.env.PLATFORM_AUTH_ENABLED === 'true';
}

/**
 * The authoritative teacher identity. In platform mode it comes exclusively
 * from the middleware-injected header; query/body teacher IDs and
 * DEFAULT_TEACHER_ID remain valid only in standalone mode.
 */
export function resolveTeacherId(req: NextRequest, standaloneFallback: string | undefined): string | null {
  if (isPlatformAuthEnabled()) {
    return req.headers.get('x-platform-user-id');
  }
  return standaloneFallback || DEFAULT_TEACHER_ID;
}

/**
 * Delegated service calls originate from the platform itself (workspace
 * provisioning); the platform already owns the course record around such a
 * call, so this service must not call back to register it again.
 */
export function isDelegatedByPlatform(req: NextRequest): boolean {
  return req.headers.get('x-platform-delegated') === 'true';
}

export function isValidCourseId(id: string): boolean {
  return /^[a-zA-Z0-9_-]{1,64}$/.test(id);
}

/** Platform mode shares the course UUID with the platform; standalone keeps the short local id. */
export function generateCourseId(explicitId?: string): string {
  return explicitId || (isPlatformAuthEnabled() ? randomUUID() : nanoid(12));
}

export interface PlatformCourseRegistration {
  id: string;
  teacherId: string;
  title: string;
  description?: string;
}

/** Semantic rejection (4xx): the platform refused this registration; retrying cannot help. */
class PlatformRegistrationRejected extends Error {}

const REGISTRATION_ATTEMPTS = 3;
const REGISTRATION_RETRY_DELAY_MS = 250;

/**
 * Register a teacher-created course with the platform. The platform endpoint
 * is idempotent (same UUID upserts), so transient failures are retried a
 * bounded number of times; 4xx semantic failures fail fast and are surfaced
 * to the caller. A caller can retry a failed registration by re-POSTing the
 * same course id to the creation route.
 */
export async function registerCourseWithPlatform(course: PlatformCourseRegistration): Promise<void> {
  if (!isPlatformAuthEnabled()) return;
  let lastError = new Error('platform registration failed');
  for (let attempt = 1; attempt <= REGISTRATION_ATTEMPTS; attempt += 1) {
    try {
      const response = await fetch(`${process.env.PLATFORM_AUTH_URL}/api/v1/internal/teacher/courses`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Teacher-Service-Key': process.env.PLATFORM_SERVICE_KEY || '',
        },
        body: JSON.stringify({
          course_id: course.id,
          teacher_id: course.teacherId,
          title: course.title,
          description: course.description,
        }),
        cache: 'no-store',
        signal: AbortSignal.timeout(5000),
      });
      if (response.ok) return;
      if (response.status < 500) {
        throw new PlatformRegistrationRejected(`platform registration failed: ${response.status}`);
      }
      lastError = new Error(`platform registration failed: ${response.status}`);
    } catch (error) {
      if (error instanceof PlatformRegistrationRejected) throw error;
      lastError = error instanceof Error ? error : new Error(String(error));
    }
    if (attempt < REGISTRATION_ATTEMPTS) {
      await new Promise((resolve) => setTimeout(resolve, REGISTRATION_RETRY_DELAY_MS));
    }
  }
  throw lastError;
}

/** Type guard for the optional platform-provided id on course creation bodies. */
export function platformProvidedCourseId(body: Partial<CreateCourseSpaceInput>): string | undefined {
  const id = (body as { id?: string }).id;
  return typeof id === 'string' && id.length > 0 ? id : undefined;
}
