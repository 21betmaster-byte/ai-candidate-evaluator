/**
 * DecisionButtons unit tests.
 *
 * Covers the manual pass/fail actions on the candidate detail page:
 *   - Default state enables both buttons
 *   - Clicking "Approve" POSTs decision=pass and refreshes
 *   - Clicking "Reject" POSTs decision=fail and refreshes
 *   - Already-decided candidates render with disabled buttons
 *   - Backend errors are surfaced as inline text
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DecisionButtons from "@/components/DecisionButtons";
import { mockRouter } from "./setup";

vi.mock("@/lib/backend", () => ({
  backend: {
    manualDecision: vi.fn(),
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

const manualDecisionMock = backend.manualDecision as ReturnType<typeof vi.fn>;

beforeEach(() => {
  manualDecisionMock.mockReset();
  manualDecisionMock.mockResolvedValue({ ok: true, status: "passed_manual" });
  mockRouter.refresh.mockReset();
});

describe("DecisionButtons", () => {
  it("enables both buttons for a manual_review candidate", () => {
    render(<DecisionButtons candidateId={1} status="manual_review" />);
    expect(screen.getByRole("button", { name: /approve to interview/i })).toBeEnabled();
    expect(screen.getByRole("button", { name: /reject candidate/i })).toBeEnabled();
  });

  it("calls manualDecision('pass') and router.refresh() on Approve", async () => {
    const user = userEvent.setup();
    render(<DecisionButtons candidateId={7} status="manual_review" />);

    await user.click(screen.getByRole("button", { name: /approve to interview/i }));

    expect(manualDecisionMock).toHaveBeenCalledWith(7, "pass");
    expect(mockRouter.refresh).toHaveBeenCalled();
  });

  it("calls manualDecision('fail') on Reject", async () => {
    const user = userEvent.setup();
    render(<DecisionButtons candidateId={7} status="manual_review" />);

    await user.click(screen.getByRole("button", { name: /reject candidate/i }));

    expect(manualDecisionMock).toHaveBeenCalledWith(7, "fail");
  });

  it("disables buttons and shows a note for already-decided candidates", () => {
    render(<DecisionButtons candidateId={7} status="passed_manual" />);
    expect(screen.getByRole("button", { name: /approve to interview/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /reject candidate/i })).toBeDisabled();
    expect(screen.getByText(/decision already recorded/i)).toBeInTheDocument();
  });

  it("disables for failed_manual too", () => {
    render(<DecisionButtons candidateId={7} status="failed_manual" />);
    expect(screen.getByRole("button", { name: /approve to interview/i })).toBeDisabled();
  });

  it("surfaces a backend error inline", async () => {
    manualDecisionMock.mockRejectedValueOnce(new BackendError(500, "boom"));
    const user = userEvent.setup();
    render(<DecisionButtons candidateId={7} status="manual_review" />);

    await user.click(screen.getByRole("button", { name: /approve to interview/i }));

    expect(await screen.findByText(/backend 500/i)).toBeInTheDocument();
  });
});
