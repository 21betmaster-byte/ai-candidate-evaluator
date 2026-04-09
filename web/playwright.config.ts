import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright config for end-to-end + visual + cross-browser tests.
 *
 * Strategy
 * --------
 * - Two webServers run in parallel:
 *     1. Tiny Node mock backend on :8765 (tests/e2e/mock-server/server.mjs)
 *     2. Next.js dev server on :3100, with BACKEND_URL pointed at the mock
 *   `page.route()` only sees browser-side traffic, so we cannot use it for
 *   server components — the mock backend covers both sides.
 * - `auth.setup.ts` runs once per browser project and persists a signed-in
 *   session to .auth/{project}.json which authenticated specs reuse.
 *
 * Projects (= browser × auth state matrix)
 * ----------------------------------------
 * setup-{chromium,firefox,webkit}
 *     Sign-in priming. Writes a per-browser auth state file.
 * authenticated-{chromium,firefox,webkit}
 *     Functional e2e + visual regression. Reuses the auth state.
 * unauthenticated-{chromium,firefox,webkit}
 *     Sign-in flow + auth-gate tests, started cold.
 *
 * Why per-browser auth files: Playwright's storageState format is browser-
 * agnostic but the cookies are scoped per-context, and running setup once
 * per browser keeps each project hermetic.
 */
const BROWSERS = [
  { name: "chromium", device: devices["Desktop Chrome"] },
  { name: "firefox", device: devices["Desktop Firefox"] },
  { name: "webkit", device: devices["Desktop Safari"] },
] as const;

function authFile(browser: string) {
  return `.auth/${browser}.json`;
}

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  // The Node mock backend is a single shared HTTP process — running tests
  // in parallel would let them stomp on each other's canned responses.
  // Single worker keeps the suite hermetic. ~26s × 3 browsers = ~80s total.
  workers: 1,
  reporter: [["list"], ["html", { open: "never" }]],
  // Visual regression: store screenshots next to the spec file with the
  // browser name in the path so each browser has its own baseline.
  snapshotPathTemplate:
    "{testDir}/__screenshots__/{testFileName}/{arg}-{projectName}{ext}",
  // Be slightly more forgiving about font / sub-pixel anti-aliasing
  // differences across OSes. Tighten later if it lets a real bug through.
  expect: {
    toHaveScreenshot: {
      maxDiffPixelRatio: 0.02,
      threshold: 0.2,
    },
  },
  use: {
    baseURL: "http://localhost:3100",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    // ---------- Setup projects: one per browser ----------
    ...BROWSERS.map(({ name, device }) => ({
      name: `setup-${name}`,
      use: device,
      testMatch: /auth\.setup\.ts/,
    })),

    // ---------- Authenticated functional + visual ----------
    ...BROWSERS.map(({ name, device }) => ({
      name: `authenticated-${name}`,
      use: { ...device, storageState: authFile(name) },
      dependencies: [`setup-${name}`],
      testIgnore: [/auth\.setup\.ts/, /sign-in\.spec\.ts/, /auth-gate\.spec\.ts/],
    })),

    // ---------- Unauthenticated (sign-in + auth gate) ----------
    ...BROWSERS.map(({ name, device }) => ({
      name: `unauthenticated-${name}`,
      use: device,
      testMatch: [/sign-in\.spec\.ts/, /auth-gate\.spec\.ts/],
    })),
  ],
  webServer: [
    {
      command: "node tests/e2e/mock-server/server.mjs",
      url: "http://localhost:8765/__mock/health",
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
      stdout: "ignore",
      stderr: "pipe",
    },
    {
      command: "npm run dev",
      url: "http://localhost:3100",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: {
        AUTH_SECRET:
          process.env.AUTH_SECRET ??
          "dev-only-not-for-prod-replace-with-openssl-rand-base64-48-AbCdEfGhIjKlMnOp",
        BACKEND_URL: "http://localhost:8765",
      },
    },
  ],
});
