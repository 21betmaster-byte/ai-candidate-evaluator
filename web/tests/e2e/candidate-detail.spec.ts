/**
 * Candidate detail e2e.
 *
 * Verifies:
 *   - Candidate with a full evaluation renders: identity, verdict, scores
 *   - Custom hiring-manager dimensions render with the right names
 *   - Awaiting-evaluation state renders cleanly
 *   - Approve POSTs the right payload and the page reflects the new status
 *   - Already-decided candidates show disabled buttons
 *   - 404 → Next's not-found page
 */
import { expect, test } from "@playwright/test";

import {
  getMockCalls,
  makeCandidateDetail,
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

test.describe("Candidate detail", () => {
  test("renders identity, verdict, and rubric sidebar", async ({ page }) => {
    await setMocks({
      "GET /api/candidates/:id": { status: 200, body: makeCandidateDetail({ id: 1 }) },
    });

    await page.goto("/candidates/1");

    await expect(page.getByRole("heading", { name: "Alice Jones" })).toBeVisible();
    await expect(page.getByText(/design-minded full-stack engineer/i)).toBeVisible();
    await expect(page.getByText(/curator's verdict/i)).toBeVisible();
    await expect(page.getByText(/strong builder with clear production impact/i)).toBeVisible();
    await expect(page.getByText(/^8\.4$/)).toBeVisible();
    await expect(page.getByText(/technical depth/i)).toBeVisible();
    await expect(page.getByText(/strong systems work/i)).toBeVisible();
  });

  test("renders custom hiring-manager dimensions", async ({ page }) => {
    const candidate = makeCandidateDetail({ id: 1 });
    candidate.current_evaluation!.scores = {
      design_taste: { score: 92, reasoning: "Sharp eye for type and spacing." },
      storytelling: { score: 78, reasoning: "Explains work like a PM." },
      builder_mindset: { score: 85, reasoning: "Ships weekly." },
    };
    await setMocks({ "GET /api/candidates/:id": { status: 200, body: candidate } });

    await page.goto("/candidates/1");

    await expect(page.getByText(/design taste/i)).toBeVisible();
    await expect(page.getByText(/storytelling/i)).toBeVisible();
    await expect(page.getByText(/builder mindset/i)).toBeVisible();
    await expect(page.getByText(/sharp eye for type and spacing/i)).toBeVisible();
  });

  test("shows 'Awaiting evaluation' when there is no current evaluation", async ({ page }) => {
    const candidate = makeCandidateDetail({ id: 2 });
    candidate.current_evaluation = null;
    await setMocks({ "GET /api/candidates/:id": { status: 200, body: candidate } });

    await page.goto("/candidates/2");
    await expect(page.getByText(/awaiting evaluation/i)).toBeVisible();
  });

  test("Approve button POSTs pass and triggers a refetch with the new status", async ({ page }) => {
    let approved = false;
    await setMocks({
      "GET /api/candidates/:id": {
        status: 200,
        body: makeCandidateDetail({ id: 5, status: "manual_review" }),
      },
      "POST /api/candidates/:id/decision": {
        status: 200,
        body: { ok: true, status: "passed_manual" },
      },
    });

    await page.goto("/candidates/5");

    // After clicking, swap the GET response to reflect the new status —
    // router.refresh() will re-fetch and the page should re-render.
    await page.getByRole("button", { name: /approve to interview/i }).click();
    await setMocks({
      "GET /api/candidates/:id": {
        status: 200,
        body: makeCandidateDetail({ id: 5, status: "passed_manual" }),
      },
    });

    await expect(page.getByText(/status · passed manual/i)).toBeVisible();

    const calls = await getMockCalls();
    expect(
      calls.some(
        (c) => c.method === "POST" && c.path === "/api/candidates/5/decision",
      ),
    ).toBe(true);
  });

  test("disables both buttons when candidate is already passed", async ({ page }) => {
    await setMocks({
      "GET /api/candidates/:id": {
        status: 200,
        body: makeCandidateDetail({ id: 5, status: "passed_manual" }),
      },
    });

    await page.goto("/candidates/5");

    await expect(
      page.getByRole("button", { name: /approve to interview/i }),
    ).toBeDisabled();
    await expect(
      page.getByRole("button", { name: /reject candidate/i }),
    ).toBeDisabled();
    await expect(page.getByText(/decision already recorded/i)).toBeVisible();
  });

  test("renders Next's 404 for an unknown candidate id", async ({ page }) => {
    await setMocks({
      "GET /api/candidates/:id": {
        status: 404,
        body: { detail: "candidate not found" },
      },
    });

    const response = await page.goto("/candidates/999");
    expect(response?.status()).toBe(404);
  });
});
