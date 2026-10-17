import { resolve } from 'node:path';
import { defineConfig } from 'vitest/config';

// Deliberately excludes setup-env.ts: this suite must never load a developer's .env.local.
export default defineConfig({
  resolve: { alias: { '@': resolve(__dirname, '.') } },
  test: {
    include: ['tests/course-space/file-management-postgres.test.ts'],
    fileParallelism: false,
  },
});
