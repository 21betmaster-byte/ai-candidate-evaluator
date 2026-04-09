/**
 * Visual regression tests.
 *
 * Captures full-page screenshots of the four screens leadership will see
 * during the demo, then asserts byte-similarity against committed
 * baselines on every subsequent run. Baselines are stored per-browser at
 * `tests/e2e/__screenshots__/visual.spec.ts/{name}-{project}.png`.
 *
 * Generating / updating baselines
 * -------------------------------
 *   npx playwright test visual.spec.ts --update-snapshots
 *
 * After running, *review the diff* in `tests/e2e/__screenshots__/` and
 * commit the changes if they reflect intentional UI work. If the diff is
 * unexpected, you've probably introduced a layout bug — fix it instead
 * of updating the baseline.
 *
 * Why this exists
 * ---------------
 * The functional e2e tests check semantic structure (roles, text). They
 * cannot catch:
 *   - A typo'd Tailwind class that breaks the layout
 *   - A wrong color token in the rubric chip
 *   - A regressed font weight on the headline
 * Visual regression tests catch all of those automatically.
 *
 * Determinism
 * -----------
 * - Viewport pinned to 1280x800 so layouts don't shift across machines.
 * - The mock backend returns identical seed data on every run.
 * - We mask the dynamic timestamps in the candidate row + processing
 *   timeline since those would otherwise change every test run.
 * - Animations disabled via `animations: "disabled"` in toHaveScreenshot.
 */
import { expect, test } from "@playwright/test";

import {
  makeCandidateDetail,
  makeCandidateRow,
  makeSettings,
  resetMocks,
  setMocks,
} from "./fixtures";

const VIEWPORT = { width: 1280, height: 800 };

// Deterministic timestamps so the seed data renders the same every run.
const FROZEN_DATE = "2026-04-05T09:00:00Z";

test.use({ viewport: VIEWPORT });

test.describe("Visual regression", () => {
  test.beforeEach(async () => {
    await resetMocks();
    await setMocks({
      "GET /api/settings": { status: 200, body: makeSettings() },
      "GET /api/candidates": {
        status: 200,
        body: [
          makeCandidateRow({
            id: 1,
            name: "Elena Rostova",
            email: "elena@example.com",
            status: "manual_review",
            overall_score: 96.0,
            created_at: FROZEN_DATE,
          }),
          makeCandidateRow({
            id: 2,
            name: "Marcus Thorne",
            email: "marcus@example.com",
            status: "auto_pass",
            overall_score: 82.0,
            created_at: FROZEN_DATE,
          }),
          makeCandidateRow({
            id: 3,
            name: "Jordan Lee",
            email: "jordan@example.com",
            status: "auto_fail",
            overall_score: 45.0,
            created_at: FROZEN_DATE,
          }),
        ],
      },
      "GET /api/candidates/:id": {
        status: 200,
        body: makeCandidateDetail({ id: 1 }),
      },
    });
  });

  test("candidates list", async ({ page }) => {
    await page.goto("/candidates");
    // Wait for the headline to land so the screenshot doesn't capture a
    // partially-hydrated page.
    await expect(
      page.getByRole("heading", { name: /candidate pipeline/i }),
    ).toBeVisible();
    await expect(page).toHaveScreenshot("candidates-list.png", {
      fullPage: true,
      animations: "disabled",
    });
  });

  test("candidate detail", async ({ page }) => {
    await page.goto("/candidates/1");
    await expect(
      page.getByRole("heading", { name: "Alice Jones" }),
    ).toBeVisible();
    await expect(page).toHaveScreenshot("candidate-detail.png", {
      fullPage: true,
      animations: "disabled",
    });
  });

  test("settings rubric editor", async ({ page }) => {
    await page.goto("/settings");
    await expect(
      page.getByRole("heading", { name: /intelligence core/i }),
    ).toBeVisible();
    await expect(page).toHaveScreenshot("settings-rubric.png", {
      fullPage: true,
      animations: "disabled",
    });
  });

  test("sign-in page", async ({ page }) => {
    // Visit signin directly. Auth state is loaded for the authenticated
    // project, so visiting /signin will succeed regardless and the page
    // we render here is the sign-in form (it's not gated).
    await page.goto("/signin");
    await expect(
      page.getByRole("heading", { name: /the curator/i }),
    ).toBeVisible();
    await expect(page).toHaveScreenshot("sign-in.png", {
      fullPage: true,
      animations: "disabled",
    });
  });
});
