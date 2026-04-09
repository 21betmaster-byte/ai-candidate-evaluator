/**
 * Poll-Now button e2e.
 *
 * The sidebar's "Poll Now" button is visible on every dashboard page, so
 * leadership will see it during every demo. It must never look stuck or
 * crash.
 */
import { expect, test } from "@playwright/test";

import { makeSettings, resetMocks, setMocks } from "./fixtures";

test.beforeEach(async () => {
  await resetMocks();
  await setMocks({
    "GET /api/settings": { status: 200, body: makeSettings() },
    "GET /api/candidates": { status: 200, body: [] },
  });
});

test.describe("Poll Now button", () => {
  test("shows the cadence hint by default", async ({ page }) => {
    await page.goto("/candidates");
    await expect(page.getByText(/auto-polls every 2 min/i)).toBeVisible();
  });

  test("shows 'X new messages' after a successful poll", async ({ page }) => {
    await setMocks({
      "POST /api/poll": { status: 200, body: { new_messages: 4 } },
    });
    await page.goto("/candidates");

    await page.getByRole("button", { name: /poll now/i }).click();
    await expect(page.getByText(/4 new messages/i)).toBeVisible();
  });

  test("shows 'up to date' on a zero-result poll", async ({ page }) => {
    await setMocks({
      "POST /api/poll": { status: 200, body: { new_messages: 0 } },
    });
    await page.goto("/candidates");

    await page.getByRole("button", { name: /poll now/i }).click();
    await expect(page.getByText(/up to date/i)).toBeVisible();
  });

  test("shows 'poll failed' on backend error, never hangs", async ({ page }) => {
    await setMocks({
      "POST /api/poll": { status: 500, body: { detail: "gmail down" } },
    });
    await page.goto("/candidates");

    await page.getByRole("button", { name: /poll now/i }).click();
    await expect(page.getByText(/poll failed/i)).toBeVisible();
    await expect(page.getByRole("button", { name: /poll now/i })).toBeEnabled();
  });
});
