import { defineConfig, devices } from "@playwright/test";

const frontendPort = process.env.FRONTEND_PORT || "3000";
const backendPort = process.env.GATEWAY_PORT || "8000";
const backendHost = process.env.GATEWAY_HOST || "127.0.0.1";
const backendBase = `http://${backendHost}:${backendPort}`;
const pythonBin = process.env.PYTHON || "./.venv/bin/python";
const backendEnv =
  "OCTOPUS_FF_REGENERATION_ENABLED=0 " +
  "OCTOPUS_FF_CAMOUFLAGE_ENABLED=0 " +
  "OCTOPUS_FF_UI_AMBIENT_SUGGESTIONS=0";

/**
 * Full-stack Playwright configuration.
 *
 * Unlike the default config, this starts both halves of the local app:
 * FastAPI backend with the deterministic offline e2e config, then Vite with
 * its /api proxy pointed at that backend. This catches the common failure mode
 * where the frontend is reachable but the backend on :8000 is stale or absent.
 */
export default defineConfig({
  testDir: "./e2e",
  testMatch: /full-stack-smoke\.spec\.ts/,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? "github" : "list",
  timeout: 45_000,

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
  ],

  webServer: [
    {
      command: `${backendEnv} ${pythonBin} -m runtime serve --config config.e2e.yaml --host ${backendHost} --port ${backendPort}`,
      url: `${backendBase}/api/status`,
      cwd: "..",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
    {
      command: `cross-env GATEWAY_PORT=${backendPort} OCTOPUS_INTERNAL_GATEWAY_BASE_URL=${backendBase} pnpm dev -- --host 0.0.0.0 --port ${frontendPort}`,
      url: `http://127.0.0.1:${frontendPort}`,
      reuseExistingServer: !process.env.CI,
      timeout: 90_000,
    },
  ],
});
