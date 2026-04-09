/**
 * PollNowButton unit tests.
 *
 * Verifies states the hiring manager will see during a demo:
 *   - idle: cadence hint ("Auto-polls every N min") + "Never polled"
 *   - pending: spinner + "Polling Inbox..." + Stop button
 *   - success: "X new messages" + IST timestamp persisted to localStorage
 *   - cancel: Stop aborts in-flight request, timestamp unchanged
 *   - error: "poll failed", timestamp unchanged
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import PollNowButton from "@/components/PollNowButton";

vi.mock("@/lib/backend", () => ({
  backend: {
    pollNow: vi.fn(),
  },
}));

import { backend } from "@/lib/backend";

const pollNowMock = backend.pollNow as ReturnType<typeof vi.fn>;

beforeEach(() => {
  pollNowMock.mockReset();
  window.localStorage.clear();
});

afterEach(() => {
  window.localStorage.clear();
});

describe("PollNowButton", () => {
  it("shows the cadence hint by default", () => {
    render(<PollNowButton pollingMinutes={5} />);
    expect(screen.getByText(/auto-polls every 5 min/i)).toBeInTheDocument();
  });

  it("shows 'X new messages' after a successful poll", async () => {
    pollNowMock.mockResolvedValueOnce({ new_messages: 3 });
    const user = userEvent.setup();
    render(<PollNowButton pollingMinutes={5} />);

    await user.click(screen.getByRole("button", { name: /poll now/i }));

    expect(await screen.findByText(/3 new messages/i)).toBeInTheDocument();
  });

  it("uses singular 'message' when exactly 1 message arrives", async () => {
    pollNowMock.mockResolvedValueOnce({ new_messages: 1 });
    const user = userEvent.setup();
    render(<PollNowButton pollingMinutes={5} />);

    await user.click(screen.getByRole("button", { name: /poll now/i }));

    expect(await screen.findByText(/1 new message$/i)).toBeInTheDocument();
  });

  it("shows 'up to date' when the poll returns zero new messages", async () => {
    pollNowMock.mockResolvedValueOnce({ new_messages: 0 });
    const user = userEvent.setup();
    render(<PollNowButton pollingMinutes={5} />);

    await user.click(screen.getByRole("button", { name: /poll now/i }));

    expect(await screen.findByText(/up to date/i)).toBeInTheDocument();
  });

  it("shows 'Never polled' when no timestamp has been persisted", () => {
    render(<PollNowButton pollingMinutes={5} />);
    expect(screen.getByText(/never polled/i)).toBeInTheDocument();
  });

  it("persists the last-polled timestamp to localStorage on success", async () => {
    pollNowMock.mockResolvedValueOnce({ new_messages: 2 });
    const user = userEvent.setup();
    render(<PollNowButton pollingMinutes={5} />);

    await user.click(screen.getByRole("button", { name: /poll now/i }));

    expect(await screen.findByText(/last polled at:.*IST/i)).toBeInTheDocument();
    expect(window.localStorage.getItem("pollNow:lastPolledAt")).toMatch(/^\d+$/);
  });

  it("hydrates the timestamp from localStorage on mount", () => {
    const ts = Date.now() - 60_000;
    window.localStorage.setItem("pollNow:lastPolledAt", String(ts));
    render(<PollNowButton pollingMinutes={5} />);
    expect(screen.getByText(/last polled at:.*IST/i)).toBeInTheDocument();
  });

  it("does NOT update the timestamp on failure", async () => {
    const err = vi.spyOn(console, "error").mockImplementation(() => {});
    pollNowMock.mockRejectedValueOnce(new Error("boom"));
    const user = userEvent.setup();
    render(<PollNowButton pollingMinutes={5} />);

    await user.click(screen.getByRole("button", { name: /poll now/i }));

    expect(await screen.findByText(/poll failed/i)).toBeInTheDocument();
    expect(screen.getByText(/never polled/i)).toBeInTheDocument();
    expect(window.localStorage.getItem("pollNow:lastPolledAt")).toBeNull();
    err.mockRestore();
  });

  it("shows Stop button while pending and aborts without updating timestamp", async () => {
    let abortedSignal: AbortSignal | undefined;
    pollNowMock.mockImplementationOnce((opts: { signal?: AbortSignal } = {}) => {
      abortedSignal = opts.signal;
      return new Promise((_resolve, reject) => {
        opts.signal?.addEventListener("abort", () => {
          const e = new Error("aborted");
          e.name = "AbortError";
          reject(e);
        });
      });
    });
    const user = userEvent.setup();
    render(<PollNowButton pollingMinutes={5} />);

    await user.click(screen.getByRole("button", { name: /poll now/i }));

    const stop = await screen.findByRole("button", { name: /stop polling/i });
    expect(screen.getByRole("button", { name: /polling inbox/i })).toBeDisabled();

    await user.click(stop);

    expect(abortedSignal?.aborted).toBe(true);
    expect(await screen.findByText(/cancelled/i)).toBeInTheDocument();
    expect(screen.getByText(/never polled/i)).toBeInTheDocument();
    expect(window.localStorage.getItem("pollNow:lastPolledAt")).toBeNull();
  });

  it("shows 'poll failed' when the backend throws", async () => {
    // Suppress the expected console.error so test output stays clean.
    const err = vi.spyOn(console, "error").mockImplementation(() => {});
    pollNowMock.mockRejectedValueOnce(new Error("boom"));
    const user = userEvent.setup();
    render(<PollNowButton pollingMinutes={5} />);

    await user.click(screen.getByRole("button", { name: /poll now/i }));

    expect(await screen.findByText(/poll failed/i)).toBeInTheDocument();
    err.mockRestore();
  });
});
