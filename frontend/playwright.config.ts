import { defineConfig, devices } from "@playwright/test";

const frontendPort = process.env.FRONTEND_PORT || "3000";

/**
 * Playwright E2E configuration for octopus-frontend.
 *
 * Expects the backend (FastAPI) on port 8000 and the frontend (Vite) on
 * port 3000. In CI, start both services before running `npx playwright test`.
 * Locally, you can let the `webServer` block below start the frontend for you.
 *
 * Usage:
 *   npx playwright test              # headless
 *   npx playwright test --ui         # interactive UI mode
 *   npx playwright test --headed     # headed browser
 */
export default defineConfig({
  testDir: "./e2e",
  // The default suite reuses a developer backend on :8000 and exercises
  // browser/UI contracts only. Specs that own isolated :13000/:18000 servers
  // belong to playwright.full.config.ts and must never leak into this lane.
  testMatch: [
    "chat.spec.ts",
    "mobile-smoke.spec.ts",
    "stream-timeline-narrative.spec.ts",
    "workflow-editor.spec.ts",
  ],
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: "html",
  timeout: 30_000,

  use: {
    baseURL: `http://127.0.0.1:${frontendPort}`,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "firefox",
      use: { ...devices["Desktop Firefox"] },
    },
  ],

  webServer: {
    command: `pnpm dev -- --host 127.0.0.1 --port ${frontendPort}`,
    url: `http://127.0.0.1:${frontendPort}`,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
