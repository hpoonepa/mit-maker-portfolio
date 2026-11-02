import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright config for the Paper Crane `apps/app` product.
 *
 * Targets the local Next dev server on port 3002 (see `next dev -p 3002` in
 * package.json). Chromium-only for speed during sprint: we'll add WebKit /
 * Firefox once auth + billing flows stabilise.
 *
 * The `webServer` block boots `next dev` automatically when the test runner
 * starts, but only if no server is already listening on 3002 (so iterating
 * locally with `pnpm dev` works without contention).
 *
 * NOTE: tests are NOT wired to run in CI yet: Agent 1 will run
 * `pnpm install` to pull `@playwright/test`, and a follow-up agent will
 * provision the Supabase test user + Stripe test mode env vars.
 */
const PORT = Number.parseInt(process.env.E2E_PORT ?? "3002", 10);
const BASE_URL = process.env.E2E_BASE_URL ?? `http://localhost:${PORT}`;
const CI = !!process.env.CI;

export default defineConfig({
  testDir: "./e2e",
  testMatch: /.*\.spec\.ts$/,
  timeout: 30_000,
  expect: { timeout: 5_000 },
  fullyParallel: true,
  forbidOnly: CI,
  retries: CI ? 2 : 0,
  workers: CI ? 1 : undefined,
  reporter: CI ? [["github"], ["html", { open: "never" }]] : "list",

  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry",
    video: "retain-on-failure",
    screenshot: "only-on-failure",
    testIdAttribute: "data-testid",
    actionTimeout: 10_000,
    navigationTimeout: 15_000,
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],

  webServer: {
    command: "pnpm dev",
    url: BASE_URL,
    reuseExistingServer: !CI,
    timeout: 120_000,
    stdout: "pipe",
    stderr: "pipe",
  },
});
