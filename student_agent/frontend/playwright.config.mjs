import { existsSync } from "node:fs";
import { defineConfig } from "@playwright/test";

const windowsChrome = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const launchOptions = process.platform === "win32" && existsSync(windowsChrome)
  ? { executablePath: windowsChrome }
  : {};

export default defineConfig({
  testDir: "./tests/e2e",
  // 默认跑「视频完 → 课后辅导」流程（开关默认开启，与生产一致）。
  // 原有四阶段编排 = 开关关闭路径，由 playwright.legacy.config.mjs
  // （AGENT_POST_VIDEO_TUTORING=0）跑 classroom-flow.spec.js。
  testMatch: /tutoring-flow\.spec\.js$/,
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
