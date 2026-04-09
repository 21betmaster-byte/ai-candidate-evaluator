/**
 * One-shot sign-in that persists a session cookie to .auth/user.json.
 * Most authenticated tests reuse this cookie via storageState so they can
 * focus on the feature under test rather than the sign-in form.
 */
import { expect, test as setup } from "@playwright/test";
import path from "node:path";

import { makeSettings, resetMocks, setMocks } from "./fixtures";

setup("authenticate", async ({ page }, testInfo) => {
  // Project name is e.g. "setup-chromium" → strip the "setup-" prefix to get
  // the browser, and write to .auth/{browser}.json so the matching
  // authenticated-{browser} project can pick it up.
  const browser = testInfo.project.name.replace(/^setup-/, "");
  const authFile = path.join(__dirname, "..", "..", ".auth", `${browser}.json`);
  // The dashboard layout fetches /settings + /candidates server-side as
  // soon as we land on /candidates. Seed both so the page renders.
  await resetMocks();
  await setMocks({
    "GET /api/settings": { status: 200, body: makeSettings() },
    "GET /api/candidates": { status: 200, body: [] },
  });

  await page.goto("/signin");
  await page.getByLabel(/email/i).fill("admin@curator.local");
  await page.getByLabel(/password/i).fill("curator");
  await page.getByRole("button", { name: /^sign in$/i }).click();

  await page.waitForURL("**/candidates");
  await expect(page).toHaveURL(/\/candidates/);

  await page.context().storageState({ path: authFile });
});
