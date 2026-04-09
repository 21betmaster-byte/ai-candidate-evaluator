/**
 * CandidateRow unit tests.
 *
 * This is the row rendered N times on the candidates hub. It's trivial
 * visually but surprisingly easy to break with edge data (null names,
 * null scores, non-ascii, long emails, unknown statuses). The demo
 * absolutely cannot render "undefined" or crash on a missing field.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import CandidateRow from "@/components/CandidateRow";
import type { CandidateRow as Row } from "@/lib/types";

function makeRow(overrides: Partial<Row> = {}): Row {
  return {
    id: 1,
    email: "alice@example.com",
    name: "Alice Jones",
    status: "manual_review",
    overall_score: 94.2,
    created_at: "2026-04-08T10:00:00Z",
    ...overrides,
  };
}

describe("CandidateRow — happy path", () => {
  it("renders name, email, and score on the 0–9.9 scale", () => {
    render(<CandidateRow row={makeRow()} />);
    expect(screen.getByText("Alice Jones")).toBeInTheDocument();
    expect(screen.getByText("alice@example.com")).toBeInTheDocument();
    // 94.2 / 10 = 9.4
    expect(screen.getByText("9.4")).toBeInTheDocument();
    expect(screen.getByText(/manual review/i)).toBeInTheDocument();
  });

  it("links to the candidate detail page", () => {
    render(<CandidateRow row={makeRow({ id: 42 })} />);
    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("href", "/candidates/42");
  });

  it("renders initials from the name", () => {
    render(<CandidateRow row={makeRow({ name: "Alice Jones" })} />);
    expect(screen.getByText("AJ")).toBeInTheDocument();
  });

  it("falls back to email initials when name is null", () => {
    render(<CandidateRow row={makeRow({ name: null, email: "bob@example.com" })} />);
    expect(screen.getByText("BO")).toBeInTheDocument();
  });
});

describe("CandidateRow — edge cases", () => {
  it("renders em-dash when overall_score is null", () => {
    render(<CandidateRow row={makeRow({ overall_score: null })} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("uses the email prefix as the name when name is null", () => {
    render(
      <CandidateRow
        row={makeRow({ name: null, email: "charlie@example.com" })}
      />,
    );
    expect(screen.getByText("charlie")).toBeInTheDocument();
  });

  it("does not crash on extremely long emails", () => {
    const longEmail = `${"x".repeat(200)}@example.com`;
    render(<CandidateRow row={makeRow({ name: null, email: longEmail })} />);
    // Just verify the row is in the DOM — layout is tailwind's job.
    expect(screen.getByRole("link")).toBeInTheDocument();
  });

  it("does not crash on unicode names", () => {
    render(<CandidateRow row={makeRow({ name: "Łukasz 日本語" })} />);
    expect(screen.getByText("Łukasz 日本語")).toBeInTheDocument();
  });

  it("renders a score of exactly 0 as 0.0", () => {
    render(<CandidateRow row={makeRow({ overall_score: 0 })} />);
    expect(screen.getByText("0.0")).toBeInTheDocument();
  });
});

describe("CandidateRow — status badges", () => {
  const cases: Array<{ status: Row["status"]; label: RegExp }> = [
    { status: "manual_review", label: /manual review/i },
    { status: "auto_pass", label: /auto-pass/i },
    { status: "auto_fail", label: /auto-fail/i },
    { status: "passed_manual", label: /passed/i },
    { status: "failed_manual", label: /failed/i },
    { status: "incomplete", label: /incomplete/i },
    { status: "pending", label: /pending/i },
    { status: "processing_error", label: /error/i },
  ];

  it.each(cases)("renders the $status badge", ({ status, label }) => {
    render(<CandidateRow row={makeRow({ status })} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });
});
