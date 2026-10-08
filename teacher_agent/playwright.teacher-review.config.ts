import { defineConfig, devices } from '@playwright/test';

// A dedicated port avoids reusing a running teacher deployment. These tests
// mock API boundaries and must not contact the platform, database or an LLM.
export default defineConfig({
  testDir: './e2e/tests',
  testMatch: 'teacher-preparation.spec.ts',
  workers: 1,
  reporter: 'list',
  use: { baseURL: 'http://127.0.0.1:3217', screenshot: 'only-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: 'pnpm exec next dev --hostname 127.0.0.1 --port 3217',
    url: 'http://127.0.0.1:3217',
    reuseExistingServer: false,
    timeout: 180000,
    env: {
      PLATFORM_AUTH_ENABLED: 'false', ACCESS_CODE: '',
      COURSE_STORAGE_MODE: 'json', COURSE_DATABASE_URL: '', DATABASE_URL: '',
      NO_PROXY: 'localhost,127.0.0.1', no_proxy: 'localhost,127.0.0.1',
    },
  },
});