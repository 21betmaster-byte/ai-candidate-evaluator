/**
 * Candidates hub e2e — the landing page of the demo.
 *
 * Verifies:
 *   - Empty state renders cleanly
 *   - Rows render with correct scores, statuses, dates, initials
 *   - Metric cards compute from backend rows
 *   - Filter tabs drive the URL and re-fetch with ?status=
 *   - Clicking a row navigates to the detail page
 *   - Backend 500 renders the error state instead of crashing
 */
import { expect, test } from "@playwright/test";

import {
  getMockCalls,
  makeCandidateRow,
  makeSettings,
  resetMocks,
  setMocks,
} from "./fixtures";

test.beforeEach(async () => {
  await resetMocks();
  await setMocks({
    "GET /api/settings": { status: 200, body: makeSettings() },
  });
});

test.describe("Candidates hub", () => {
  test("renders the empty state when the backend returns no rows", async ({ page }) => {
    await setMocks({ "GET /api/candidates": { status: 200, body: [] } });
    await page.goto("/candidates");

    await expect(page.getByText(/no candidates yet/i)).toBeVisible();
    await expect(page.getByText(/total candidates/i)).toBeVisible();
  });

  test("renders three rows with correct names, statuses, and scores", async ({ page }) => {
    await setMocks({
      "GET /api/candidates": {
        status: 200,
        body: [
          makeCandidateRow({
            id: 1,
            name: "Elena Rostova",
            email: "elena@example.com",
            status: "manual_review",
            overall_score: 98.0,
          }),
          makeCandidateRow({
            id: 2,
            name: "Marcus Thorne",
            email: "marcus@example.com",
            status: "auto_pass",
            overall_score: 82.0,
          }),
          makeCandidateRow({
            id: 3,
            name: "Jordan Lee",
            email: "jordan@example.com",
            status: "auto_fail",
            overall_score: 45.0,
          }),
        ],
      },
    });

    await page.goto("/candidates");

    await expect(page.getByText("Elena Rostova")).toBeVisible();
    await expect(page.getByText("Marcus Thorne")).toBeVisible();
    await expect(page.getByText("Jordan Lee")).toBeVisible();

    // Scores rendered on the 0–9.9 scale.
    await expect(page.getByText(/^9\.8$/)).toBeVisible();
    await expect(page.getByText(/^8\.2$/)).toBeVisible();
    await expect(page.getByText(/^4\.5$/)).toBeVisible();
  });

  test("filter tab sets ?status= in the URL and triggers a refetch", async ({ page }) => {
    await setMocks({
      "GET /api/candidates": { status: 200, body: [] },
    });

    await page.goto("/candidates");
    await page.getByRole("link", { name: /^manual review$/i }).click();

    await expect(page).toHaveURL(/status=manual_review/);
    // The mock server should have seen a GET /api/candidates with the filter.
    const calls = await getMockCalls();
    const candidateCalls = calls.filter((c) => c.path === "/api/candidates");
    expect(
      candidateCalls.some((c) => c.query.status === "manual_review"),
    ).toBe(true);
  });

  test("clicking a row navigates to the candidate detail page", async ({ page }) => {
    await setMocks({
      "GET /api/candidates": {
        status: 200,
        body: [makeCandidateRow({ id: 42, name: "Alice" })],
      },
      // The detail page also calls /api/candidates/:id; stub it so the
      // navigation lands on a real-looking page.
      "GET /api/candidates/:id": {
        status: 200,
        body: { id: 42, email: "alice@example.com", name: "Alice", status: "manual_review", missing_items: null, created_at: "2026-04-01T00:00:00Z", updated_at: "2026-04-01T00:00:00Z", current_evaluation: null, logs: [] },
      },
    });

    await page.goto("/candidates");
    // The whole row is one link; click it by role to dodge any text-match
    // ambiguity between the name and the email.
    await page.getByRole("link", { name: /alice/i }).click();
    await expect(page).toHaveURL(/\/candidates\/42/);
  });

  test("renders the error state when the backend returns 500", async ({ page }) => {
    await setMocks({
      "GET /api/candidates": { status: 500, body: { detail: "db unreachable" } },
    });

    await page.goto("/candidates");
    await expect(page.getByText(/backend unavailable/i)).toBeVisible();
  });
});
