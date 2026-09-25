import { existsSync } from "node:fs";
import { defineConfig } from "@playwright/test";

const windowsChrome = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const launchOptions = process.platform === "win32" && existsSync(windowsChrome)
  ? { executablePath: windowsChrome }
  : {};

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:8877",
    headless: true,
    launchOptions,
    trace: "retain-on-failure"
  },
  webServer: {
    command: "python ../apps/start.py --no-browser --port 8877",
    url: "http://127.0.0.1:8877/api/student/courses",
    reuseExistingServer: false,
    timeout: 30_000,
    env: {
      ...process.env,
      AGENT_TICK_SECONDS: "3600",
      AGENT_LLM_API_KEY: ""
    }
  }
});
