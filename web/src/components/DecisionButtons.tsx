"use client";
/**
 * Manual pass/fail controls on the candidate detail page.
 * Posts to /api/backend/candidates/{id}/decision and, on success, forces a
 * router refresh so the detail page re-fetches the candidate's new status.
 */
import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";

import { backend, BackendError } from "@/lib/backend";

export default function DecisionButtons({
  candidateId,
  status,
}: {
  candidateId: number;
  status: string;
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const alreadyDecided =
    status === "passed_manual" || status === "failed_manual";

  function submit(decision: "pass" | "fail") {
    setError(null);
    startTransition(async () => {
      try {
        await backend.manualDecision(candidateId, decision);
        router.refresh();
      } catch (err) {
        setError(err instanceof BackendError ? err.message : "decision failed");
      }
    });
  }

  return (
    <div className="flex flex-col items-end gap-2">
      <div className="flex gap-4">
        <button
          onClick={() => submit("fail")}
          disabled={pending || alreadyDecided}
          className="px-8 py-4 bg-surface-container-highest text-on-surface rounded-full font-bold text-sm tracking-tight active:scale-95 transition-transform disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {pending ? "…" : "Reject Candidate"}
        </button>
        <button
          onClick={() => submit("pass")}
          disabled={pending || alreadyDecided}
          className="px-8 py-4 bg-gradient-to-br from-primary to-primary/80 text-on-primary rounded-full font-bold text-sm tracking-tight shadow-[0px_12px_32px_rgba(255,71,87,0.25)] active:scale-95 transition-transform disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {pending ? "…" : "Approve to Interview"}
        </button>
      </div>
      {alreadyDecided && (
        <p className="text-xs opacity-60">Decision already recorded — {status.replace("_", " ")}.</p>
      )}
      {error && <p className="text-xs text-error">{error}</p>}
    </div>
  );
}
