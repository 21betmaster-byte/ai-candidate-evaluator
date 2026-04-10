"use client";
/**
 * Poll-Now button in the sidebar. Triggers POST /api/backend/poll, which
 * asks the backend to run a single Gmail inbox poll synchronously.
 *
 * While a poll is in flight the Poll Now button is disabled and a Stop
 * button appears so the user can abort a long-running poll. The
 * "Last polled at" timestamp (IST) is persisted to localStorage and only
 * updates on successful completion — not on cancel or failure.
 */
import { useEffect, useRef, useState } from "react";
import { backend } from "@/lib/backend";

const LAST_POLLED_AT_KEY = "pollNow:lastPolledAt";

function formatIST(ts: number): string {
  const formatted = new Intl.DateTimeFormat("en-IN", {
    timeZone: "Asia/Kolkata",
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(new Date(ts));
  return `${formatted} IST`;
}

export default function PollNowButton({ pollingMinutes, serverLastPolledAt }: { pollingMinutes: number; serverLastPolledAt?: string | null }) {
  const [pending, setPending] = useState(false);
  const [lastResult, setLastResult] = useState<string | null>(null);
  const [lastPolledAt, setLastPolledAt] = useState<number | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Hydrate persisted timestamp after mount to avoid SSR mismatch.
  // Use the most recent of localStorage (manual polls) and the server
  // timestamp (auto + manual polls) so the UI always shows the latest.
  useEffect(() => {
    let localTs: number | null = null;
    try {
      const raw = window.localStorage.getItem(LAST_POLLED_AT_KEY);
      if (raw) {
        const parsed = Number(raw);
        if (Number.isFinite(parsed)) localTs = parsed;
      }
    } catch (err) {
      console.warn("[PollNow] failed to read lastPolledAt from localStorage", err);
    }

    const serverTs = serverLastPolledAt ? new Date(serverLastPolledAt).getTime() : null;
    const best = [localTs, serverTs].filter((t): t is number => t !== null && Number.isFinite(t));
    if (best.length > 0) {
      setLastPolledAt(Math.max(...best));
    }
  }, [serverLastPolledAt]);

  async function onClick() {
    if (pending) return;
    const controller = new AbortController();
    abortRef.current = controller;
    const startedAt = Date.now();
    setPending(true);
    console.info("[PollNow] start", { at: new Date(startedAt).toISOString() });

    try {
      const { new_messages } = await backend.pollNow({ signal: controller.signal });
      const now = Date.now();
      const durationMs = now - startedAt;
      console.info("[PollNow] success", { newMessages: new_messages, durationMs });
      setLastResult(
        new_messages > 0
          ? `${new_messages} new ${new_messages === 1 ? "message" : "messages"}`
          : "up to date",
      );
      setLastPolledAt(now);
      try {
        window.localStorage.setItem(LAST_POLLED_AT_KEY, String(now));
      } catch (err) {
        console.warn("[PollNow] failed to persist lastPolledAt", err);
      }
    } catch (err) {
      const durationMs = Date.now() - startedAt;
      const aborted =
        controller.signal.aborted ||
        (err instanceof DOMException && err.name === "AbortError") ||
        (err instanceof Error && err.name === "AbortError");
      if (aborted) {
        console.info("[PollNow] cancelled", { durationMs });
        setLastResult("cancelled");
      } else {
        console.error("[PollNow] failed", { error: err, durationMs });
        setLastResult("poll failed");
      }
    } finally {
      abortRef.current = null;
      setPending(false);
    }
  }

  function onStop() {
    if (!abortRef.current) return;
    console.info("[PollNow] stop requested");
    abortRef.current.abort();
  }

  return (
    <div className="space-y-2">
      <button
        onClick={onClick}
        disabled={pending}
        className={
          pending
            ? "w-full flex items-center justify-center gap-2 py-3 bg-on-surface/10 text-on-surface/40 font-headline font-bold rounded-full cursor-not-allowed"
            : "w-full flex items-center justify-center gap-2 py-3 bg-primary text-on-primary font-headline font-bold rounded-full hover:brightness-110 active:scale-95 transition-all"
        }
      >
        {pending ? (
          <>
            <span className="material-symbols-outlined text-sm animate-spin-custom">sync</span>
            <span className="text-xs">Polling Inbox...</span>
          </>
        ) : (
          <>
            <span className="material-symbols-outlined text-sm">sync</span>
            <span className="text-xs">Poll Now</span>
          </>
        )}
      </button>

      <p className="text-[10px] text-center opacity-70 font-semibold">
        {lastPolledAt
          ? `Last polled at: ${formatIST(lastPolledAt)}`
          : "Never polled"}
      </p>

      {pending && (
        <button
          onClick={onStop}
          className="w-full flex items-center justify-center gap-2 py-2 bg-error/10 text-error font-headline font-bold rounded-full hover:bg-error/20 active:scale-95 transition-all"
        >
          <span className="material-symbols-outlined text-sm">stop_circle</span>
          <span className="text-xs">Stop Polling</span>
        </button>
      )}

      <p className="text-[10px] text-center opacity-60 font-semibold">
        {lastResult
          ? `Last poll: ${lastResult}`
          : `Auto-polls every ${pollingMinutes} min`}
      </p>
    </div>
  );
}
