import { afterEach, describe, expect, it } from 'vitest';
import {
  getCourseDatabaseHealth,
  getCourseDatabaseUrl,
  isCourseDatabaseConfigured,
} from '@/lib/server/course-space-database';

const originalCourseUrl = process.env.COURSE_DATABASE_URL;
const originalDatabaseUrl = process.env.DATABASE_URL;

afterEach(() => {
  if (originalCourseUrl === undefined) delete process.env.COURSE_DATABASE_URL;
  else process.env.COURSE_DATABASE_URL = originalCourseUrl;
  if (originalDatabaseUrl === undefined) delete process.env.DATABASE_URL;
  else process.env.DATABASE_URL = originalDatabaseUrl;
});

describe('course space database configuration', () => {
  it('supports local fallback when no PostgreSQL URL is configured', async () => {
    delete process.env.COURSE_DATABASE_URL;
    delete process.env.DATABASE_URL;
    expect(isCourseDatabaseConfigured()).toBe(false);
    await expect(getCourseDatabaseHealth()).resolves.toEqual({
      configured: false,
      connected: false,
      driver: 'postgresql',
    });
  });

  it('prefers the dedicated course database URL', () => {
    process.env.DATABASE_URL = 'postgresql://shared/database';
    process.env.COURSE_DATABASE_URL = 'postgresql://course/database';
    expect(getCourseDatabaseUrl()).toBe('postgresql://course/database');
  });
});
