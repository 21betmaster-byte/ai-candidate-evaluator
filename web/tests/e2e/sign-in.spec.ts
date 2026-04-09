/**
 * Sign-in flow e2e.
 *
 * Exercises the real Credentials provider end-to-end:
 *   1. Happy path with the default test user
 *   2. Wrong password shows the inline error
 *   3. Unknown email shows the inline error
 *   4. `from` query param is honored after sign-in
 *
 * These tests live in the `unauthenticated` project so they don't inherit
 * the shared signed-in storageState.
 */
import { expect, test } from "@playwright/test";

import { makeSettings, resetMocks, setMocks } from "./fixtures";

test.beforeEach(async () => {
  await resetMocks();
  // After sign-in we land on /candidates which fetches /settings + /candidates
  // server-side; seed both so the layout doesn't error.
  await setMocks({
    "GET /api/settings": { status: 200, body: makeSettings() },
    "GET /api/candidates": { status: 200, body: [] },
  });
});

test.describe("Sign in", () => {
  test("signs in with the default test credentials", async ({ page }) => {
    await page.goto("/signin");
    await expect(page.getByRole("heading", { name: /the curator/i })).toBeVisible();

    await page.getByRole("button", { name: /^sign in$/i }).click();
    await page.waitForURL("**/candidates");
    await expect(page).toHaveURL(/\/candidates/);
  });

  test("rejects wrong password and shows the inline error", async ({ page }) => {
    await page.goto("/signin");

    await page.getByLabel(/password/i).fill("not-the-password");
    await page.getByRole("button", { name: /^sign in$/i }).click();

    await expect(page.getByText(/invalid email or password/i)).toBeVisible();
    await expect(page).toHaveURL(/error=1/);
  });

  test("rejects unknown email", async ({ page }) => {
    await page.goto("/signin");

    await page.getByLabel(/email/i).fill("nobody@elsewhere.com");
    await page.getByRole("button", { name: /^sign in$/i }).click();

    await expect(page.getByText(/invalid email or password/i)).toBeVisible();
  });

  test("honors the `from` redirect after a successful sign-in", async ({ page }) => {
    // Navigating to a protected page redirects to /signin?from=/settings.
    await page.goto("/settings");
    await expect(page).toHaveURL(/\/signin\?from=%2Fsettings/);

    await page.getByRole("button", { name: /^sign in$/i }).click();
    await page.waitForURL("**/settings");
    await expect(page).toHaveURL(/\/settings$/);
  });
});
