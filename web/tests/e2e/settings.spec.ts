/**
 * Settings page e2e — the demo's centerpiece.
 *
 * Scenarios covered:
 *   1. Page loads the current rubric from the backend
 *   2. Editing a description and saving round-trips a PUT with the new payload
 *   3. Adding a brand-new "design_taste" dimension with description + weight
 *   4. Removing a dimension and redistributing weights
 *   5. Save disabled when weights don't sum to 100
 *   6. Backend 400 errors are surfaced to the user
 *   7. Threshold inputs round-trip
 *   8. Company name + pass email text round-trip
 */
import { expect, test } from "@playwright/test";

import {
  getMockCalls,
  makeSettings,
  resetMocks,
  setMocks,
} from "./fixtures";

import type { SettingsModel } from "../../src/lib/types";

async function lastPutSettingsBody(): Promise<SettingsModel | null> {
  const calls = await getMockCalls();
  const puts = calls.filter(
    (c) => c.method === "PUT" && c.path === "/api/settings",
  );
  if (puts.length === 0) return null;
  return puts[puts.length - 1].body as SettingsModel;
}

test.beforeEach(async () => {
  await resetMocks();
  await setMocks({
    "GET /api/settings": { status: 200, body: makeSettings() },
    "PUT /api/settings": { status: 200, body: makeSettings() },
  });
});

test.describe("Settings — rubric editor", () => {
  test("loads the existing rubric into the form", async ({ page }) => {
    await page.goto("/settings");

    await expect(
      page.getByRole("heading", { name: /intelligence core/i }),
    ).toBeVisible();
    await expect(page.locator('input[value="technical depth"]')).toBeVisible();
    await expect(page.locator('input[value="shipped products"]')).toBeVisible();
    await expect(page.locator('input[value="business thinking"]')).toBeVisible();
    await expect(page.getByText(/balanced: 100%/i)).toBeVisible();
  });

  test("editing a description and saving posts a PUT with the new text", async ({ page }) => {
    await page.goto("/settings");

    const firstDescription = page
      .getByPlaceholder(/what does opus measure/i)
      .first();
    await firstDescription.fill("Deep engineering chops with production receipts.");

    await page.getByRole("button", { name: /save settings/i }).click();
    await expect(page.getByText(/^saved$/i)).toBeVisible();

    const saved = await lastPutSettingsBody();
    expect(saved).not.toBeNull();
    expect(saved!.rubric[0].description).toBe(
      "Deep engineering chops with production receipts.",
    );
    expect(saved!.rubric[0].key).toBe("technical_depth");
  });

  test("adds a new custom dimension, distributes evenly, and saves", async ({ page }) => {
    await page.goto("/settings");

    await page.getByRole("button", { name: /add dimension/i }).click();

    const names = page.getByPlaceholder(/dimension name/i);
    await names.nth(3).fill("Design Taste");

    // Auto-slugify populates the key.
    const keys = page.getByPlaceholder("dimension_key");
    await expect(keys.nth(3)).toHaveValue("design_taste");

    const descriptions = page.getByPlaceholder(/what does opus measure/i);
    await descriptions
      .nth(3)
      .fill("Eye for visual craft — proportion, restraint, tasteful motion.");

    await page.getByRole("button", { name: /distribute evenly/i }).click();

    await page.getByRole("button", { name: /save settings/i }).click();
    await expect(page.getByText(/^saved$/i)).toBeVisible();

    const saved = await lastPutSettingsBody();
    expect(saved).not.toBeNull();
    expect(saved!.rubric).toHaveLength(4);
    const taste = saved!.rubric.find((d) => d.key === "design_taste");
    expect(taste).toBeTruthy();
    expect(taste!.description).toContain("Eye for visual craft");
    expect(saved!.rubric.reduce((s, d) => s + d.weight, 0)).toBe(100);
  });

  test("removing a dimension and redistributing keeps the form valid", async ({ page }) => {
    await page.goto("/settings");

    const removeButtons = page.getByRole("button", { name: /^remove$/i });
    await removeButtons.first().click();

    // Now 2 dimensions remain (35 + 25 = 60).
    await expect(page.getByText(/sum: 60%/i)).toBeVisible();
    await expect(
      page.getByRole("button", { name: /save settings/i }),
    ).toBeDisabled();

    await page.getByRole("button", { name: /distribute evenly/i }).click();
    await expect(page.getByText(/balanced: 100%/i)).toBeVisible();
    await expect(
      page.getByRole("button", { name: /save settings/i }),
    ).toBeEnabled();
  });

  test("surfaces a backend 400 error from Save", async ({ page }) => {
    await setMocks({
      "PUT /api/settings": {
        status: 400,
        body: {
          detail: "thresholds must be ordered: auto_fail < manual_review < auto_pass",
        },
      },
    });

    await page.goto("/settings");
    const descriptions = page.getByPlaceholder(/what does opus measure/i);
    await descriptions.first().fill("Updated description.");

    await page.getByRole("button", { name: /save settings/i }).click();

    await expect(page.getByText(/thresholds must be ordered/i)).toBeVisible();
  });

  test("threshold + company + pass-email round-trip in a single save", async ({ page }) => {
    await page.goto("/settings");

    await page.locator("input[value='Curator']").fill("Plum Builders");
    // The pass-email textarea has a unique placeholder; target by that.
    await page
      .getByPlaceholder(/what to tell passing candidates/i)
      .fill("Reply with three slots and we'll confirm.");

    // Find the threshold inputs by their numeric values from the seed.
    const autoPass = page.locator('input[type="number"][value="70"]').first();
    const manualReview = page.locator('input[type="number"][value="69"]').first();
    await autoPass.fill("80");
    await manualReview.fill("75");

    await page.getByRole("button", { name: /save settings/i }).click();
    await expect(page.getByText(/^saved$/i)).toBeVisible();

    const saved = await lastPutSettingsBody();
    expect(saved).not.toBeNull();
    expect(saved!.tier_thresholds.auto_pass_floor).toBe(80);
    expect(saved!.tier_thresholds.manual_review_ceiling).toBe(75);
    expect(saved!.company_name).toBe("Plum Builders");
    expect(saved!.pass_next_steps_text).toContain("three slots");
  });
});
