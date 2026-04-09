/**
 * Auth gate: unauthenticated users hitting protected pages must be
 * redirected to /signin with a `from` query param.
 */
import { expect, test } from "@playwright/test";

import { makeSettings, resetMocks, setMocks } from "./fixtures";

test.beforeEach(async () => {
  await resetMocks();
  await setMocks({
    "GET /api/settings": { status: 200, body: makeSettings() },
  });
});

test.describe("Auth gate", () => {
  test("redirects unauthenticated /candidates to /signin", async ({ page }) => {
    await page.goto("/candidates");
    await expect(page).toHaveURL(/\/signin\?from=%2Fcandidates/);
  });

  test("redirects unauthenticated /settings to /signin", async ({ page }) => {
    await page.goto("/settings");
    await expect(page).toHaveURL(/\/signin\?from=%2Fsettings/);
  });

  test("redirects unauthenticated /candidates/42 to /signin", async ({ page }) => {
    await page.goto("/candidates/42");
    await expect(page).toHaveURL(/\/signin\?from=%2Fcandidates%2F42/);
  });
});
