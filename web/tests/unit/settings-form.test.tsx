/**
 * SettingsForm unit tests — the demo-critical rubric editor.
 *
 * What this file is protecting:
 *   1. Client-side validation mirrors the backend's pydantic rules exactly
 *      (weights==100, unique keys, ordered thresholds, non-blank descriptions).
 *   2. Auto-slugify works (name → key) and stops once the user touches the
 *      key directly.
 *   3. Adding and removing dimensions behaves sanely (can't remove last one).
 *   4. "Distribute evenly" actually sums to 100 including the remainder.
 *   5. Save payload sent to the backend matches what the user sees on screen.
 *   6. Save failures surface to the user.
 *
 * Any regression in these will be visible in the leadership demo in seconds,
 * so the suite is intentionally exhaustive.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach } from "vitest";

import SettingsForm from "@/components/SettingsForm";
import type { SettingsModel } from "@/lib/types";

// Mock the backend helper — we only verify what this form sends.
vi.mock("@/lib/backend", () => ({
  backend: {
    updateSettings: vi.fn(),
  },
  BackendError: class BackendError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(`backend ${status}: ${message}`);
      this.status = status;
    }
  },
}));

import { backend, BackendError } from "@/lib/backend";

const updateSettingsMock = backend.updateSettings as ReturnType<typeof vi.fn>;

function makeSettings(overrides: Partial<SettingsModel> = {}): SettingsModel {
  return {
    polling_minutes: 2,
    rubric: [
      { key: "technical_depth", description: "engineering chops", weight: 50 },
      { key: "shipped_products", description: "track record of launches", weight: 50 },
    ],
    tier_thresholds: {
      auto_fail_ceiling: 49,
      manual_review_ceiling: 69,
      auto_pass_floor: 70,
    },
    pass_next_steps_text: "Reply with times.",
    reminder_hours: 48,
    incomplete_expiry_days: 7,
    company_name: "Curator",
    ...overrides,
  };
}

beforeEach(() => {
  updateSettingsMock.mockReset();
  updateSettingsMock.mockImplementation(async (body: SettingsModel) => body);
});

// --------------------------------------------------------------------------
// Render + initial state
// --------------------------------------------------------------------------

describe("SettingsForm — initial render", () => {
  it("renders every rubric dimension that came in from the backend", () => {
    render(<SettingsForm initial={makeSettings()} />);
    const dims = screen.getAllByPlaceholderText(/dimension name/i);
    expect(dims).toHaveLength(2);
    expect((dims[0] as HTMLInputElement).value).toBe("technical depth");
    expect((dims[1] as HTMLInputElement).value).toBe("shipped products");
  });

  it("shows 'Balanced: 100%' chip when weights sum to 100", () => {
    render(<SettingsForm initial={makeSettings()} />);
    expect(screen.getByText(/balanced: 100%/i)).toBeInTheDocument();
  });

  it("populates company name + polling + threshold inputs", () => {
    render(<SettingsForm initial={makeSettings()} />);
    expect(screen.getByDisplayValue("Curator")).toBeInTheDocument();
    expect(screen.getByText(/every 2 min/i)).toBeInTheDocument();
    expect(screen.getByDisplayValue("70")).toBeInTheDocument(); // auto_pass
    expect(screen.getByDisplayValue("49")).toBeInTheDocument(); // auto_fail
  });
});

// --------------------------------------------------------------------------
// Validation — client mirrors backend invariants
// --------------------------------------------------------------------------

describe("SettingsForm — validation", () => {
  it("shows 'weights must sum to 100' when the user edits a weight", async () => {
    render(<SettingsForm initial={makeSettings()} />);

    // Drop the first weight slider to 10 → total 60.
    // Range inputs in jsdom need fireEvent.change, not userEvent.
    const sliders = screen.getAllByRole("slider");
    fireEvent.change(sliders[0], { target: { value: "10" } });

    expect(await screen.findByText(/sum: 60%/i)).toBeInTheDocument();
    expect(screen.getByText(/weights must sum to 100/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /save settings/i })).toBeDisabled();
  });

  it("shows a duplicate-key error when two dimensions share a key", async () => {
    const user = userEvent.setup();
    render(<SettingsForm initial={makeSettings()} />);

    // Type a duplicate key directly into the second dimension's key field.
    const keyFields = screen.getAllByPlaceholderText("dimension_key");
    await user.clear(keyFields[1]);
    await user.type(keyFields[1], "technical_depth");

    expect(
      await screen.findByText(/duplicate key: technical_depth/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /save settings/i })).toBeDisabled();
  });

  it("shows an error when a dimension has a blank description", async () => {
    const user = userEvent.setup();
    render(<SettingsForm initial={makeSettings()} />);

    const descriptions = screen.getAllByPlaceholderText(/what does opus measure/i);
    await user.clear(descriptions[0]);

    expect(
      await screen.findByText(/needs a description/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /save settings/i })).toBeDisabled();
  });

  it("shows an error when thresholds are out of order", async () => {
    const user = userEvent.setup();
    render(<SettingsForm initial={makeSettings()} />);

    // auto_fail should be < manual_review < auto_pass. Make auto_fail >
    // manual_review to trip it.
    const inputs = screen.getAllByRole("spinbutton") as HTMLInputElement[];
    // Last of the threshold rows: auto_pass, manual_review, auto_fail.
    // The form renders them in that visual order.
    const autoFailInput = inputs.find((i) => i.value === "49");
    expect(autoFailInput).toBeDefined();
    await user.clear(autoFailInput!);
    await user.type(autoFailInput!, "90");

    expect(
      await screen.findByText(/thresholds must be ordered/i),
    ).toBeInTheDocument();
  });

  it("shows an invalid-key error for a non-slug key", async () => {
    const user = userEvent.setup();
    render(<SettingsForm initial={makeSettings()} />);

    const keyFields = screen.getAllByPlaceholderText("dimension_key");
    await user.clear(keyFields[0]);
    // The input onChange lowercases, so "has space" survives the lowercasing
    // but still fails the slug regex.
    await user.type(keyFields[0], "has space");

    expect(
      await screen.findByText(/not a valid key/i),
    ).toBeInTheDocument();
  });
});

// --------------------------------------------------------------------------
// Auto-slugify
// --------------------------------------------------------------------------

describe("SettingsForm — auto-slugify", () => {
  it("derives the key from the name until the user touches the key", async () => {
    const user = userEvent.setup();
    // Start with a fresh rubric so the 'untouched' state applies.
    const initial = makeSettings({
      rubric: [{ key: "", description: "desc", weight: 100 }],
    });
    render(<SettingsForm initial={initial} />);

    const nameField = screen.getByPlaceholderText(/dimension name/i) as HTMLInputElement;
    await user.clear(nameField);
    await user.type(nameField, "Design Taste");

    const keyField = screen.getByPlaceholderText("dimension_key") as HTMLInputElement;
    expect(keyField.value).toBe("design_taste");
  });

  it("stops auto-deriving after the user manually edits the key", async () => {
    const user = userEvent.setup();
    const initial = makeSettings({
      rubric: [{ key: "", description: "desc", weight: 100 }],
    });
    render(<SettingsForm initial={initial} />);

    const nameField = screen.getByPlaceholderText(/dimension name/i) as HTMLInputElement;
    const keyField = screen.getByPlaceholderText("dimension_key") as HTMLInputElement;

    await user.type(nameField, "Design");
    expect(keyField.value).toBe("design");

    // Manually override.
    await user.clear(keyField);
    await user.type(keyField, "visual_craft");

    // Further name changes must NOT clobber the manual key.
    await user.clear(nameField);
    await user.type(nameField, "Brand Fit");
    expect(keyField.value).toBe("visual_craft");
  });
});

// --------------------------------------------------------------------------
// Add / remove dimensions
// --------------------------------------------------------------------------

describe("SettingsForm — add/remove", () => {
  it("adds a new blank dimension row on click", async () => {
    const user = userEvent.setup();
    render(<SettingsForm initial={makeSettings()} />);

    await user.click(screen.getByRole("button", { name: /add dimension/i }));

    const dims = screen.getAllByPlaceholderText(/dimension name/i);
    expect(dims).toHaveLength(3);
  });

  it("removes a dimension when the user clicks Remove", async () => {
    const user = userEvent.setup();
    render(<SettingsForm initial={makeSettings()} />);

    const removeButtons = screen.getAllByRole("button", { name: /^remove$/i });
    await user.click(removeButtons[0]);

    const dims = screen.getAllByPlaceholderText(/dimension name/i);
    expect(dims).toHaveLength(1);
  });

  it("hides the Remove button when only one dimension remains", () => {
    render(
      <SettingsForm
        initial={makeSettings({
          rubric: [{ key: "only_one", description: "x", weight: 100 }],
        })}
      />,
    );
    expect(screen.queryByRole("button", { name: /^remove$/i })).toBeNull();
  });
});

// --------------------------------------------------------------------------
// Distribute evenly
// --------------------------------------------------------------------------

describe("SettingsForm — distribute evenly", () => {
  it("splits weights into chunks that sum to exactly 100", async () => {
    const user = userEvent.setup();
    render(
      <SettingsForm
        initial={makeSettings({
          rubric: [
            { key: "a", description: "x", weight: 10 },
            { key: "b", description: "x", weight: 10 },
            { key: "c", description: "x", weight: 10 },
          ],
        })}
      />,
    );

    await user.click(screen.getByRole("button", { name: /distribute evenly/i }));

    expect(await screen.findByText(/balanced: 100%/i)).toBeInTheDocument();
  });
});

// --------------------------------------------------------------------------
// Save payload
// --------------------------------------------------------------------------

describe("SettingsForm — save", () => {
  it("sends the current editor state to backend.updateSettings", async () => {
    const user = userEvent.setup();
    render(<SettingsForm initial={makeSettings()} />);

    // Edit a description so we can assert it round-trips into the payload.
    const descriptions = screen.getAllByPlaceholderText(/what does opus measure/i);
    await user.clear(descriptions[0]);
    await user.type(descriptions[0], "new description for technical depth");

    await user.click(screen.getByRole("button", { name: /save settings/i }));

    expect(updateSettingsMock).toHaveBeenCalledTimes(1);
    const payload = updateSettingsMock.mock.calls[0][0] as SettingsModel;
    expect(payload.rubric[0].description).toBe("new description for technical depth");
    expect(payload.rubric[0].key).toBe("technical_depth");
    expect(payload.rubric[0].weight).toBe(50);
    expect(payload.rubric[1].key).toBe("shipped_products");
    expect(payload.tier_thresholds.auto_pass_floor).toBe(70);
    expect(payload.company_name).toBe("Curator");
  });

  it("trims whitespace from keys and descriptions before sending", async () => {
    const user = userEvent.setup();
    render(<SettingsForm initial={makeSettings()} />);

    const descriptions = screen.getAllByPlaceholderText(/what does opus measure/i);
    await user.clear(descriptions[0]);
    await user.type(descriptions[0], "  padded description  ");

    await user.click(screen.getByRole("button", { name: /save settings/i }));

    const payload = updateSettingsMock.mock.calls[0][0] as SettingsModel;
    expect(payload.rubric[0].description).toBe("padded description");
  });

  it("shows 'Saved' after a successful round-trip", async () => {
    const user = userEvent.setup();
    render(<SettingsForm initial={makeSettings()} />);

    await user.click(screen.getByRole("button", { name: /save settings/i }));

    expect(await screen.findByText(/saved/i)).toBeInTheDocument();
  });

  it("surfaces backend errors to the user", async () => {
    updateSettingsMock.mockRejectedValueOnce(
      new BackendError(400, "rubric weights must sum to 100 (got 99)"),
    );
    const user = userEvent.setup();
    render(<SettingsForm initial={makeSettings()} />);

    await user.click(screen.getByRole("button", { name: /save settings/i }));

    expect(
      await screen.findByText(/rubric weights must sum to 100/i),
    ).toBeInTheDocument();
  });

  it("does not call the backend when validation is failing", async () => {
    const user = userEvent.setup();
    render(<SettingsForm initial={makeSettings()} />);

    // Break the rubric by clearing a description.
    const descriptions = screen.getAllByPlaceholderText(/what does opus measure/i);
    await user.clear(descriptions[0]);

    // Save button should be disabled; clicking does nothing.
    const saveBtn = screen.getByRole("button", { name: /save settings/i });
    expect(saveBtn).toBeDisabled();
    await user.click(saveBtn);

    expect(updateSettingsMock).not.toHaveBeenCalled();
  });
});
