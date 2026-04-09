import { headers } from "next/headers";
import Link from "next/link";

import CandidateRow from "@/components/CandidateRow";
import { backend } from "@/lib/backend";
import type { CandidateRow as Row } from "@/lib/types";

export const dynamic = "force-dynamic";

const FILTERS: { key: string; label: string }[] = [
  { key: "", label: "All" },
  { key: "manual_review", label: "Manual Review" },
  { key: "auto_pass", label: "Auto-Pass" },
  { key: "auto_fail", label: "Auto-Fail" },
  { key: "incomplete", label: "Incomplete" },
  { key: "processing_error", label: "Errors" },
];

const SORTS: { key: string; label: string }[] = [
  { key: "created_desc", label: "Newest" },
  { key: "created_asc", label: "Oldest" },
  { key: "score_desc", label: "Score ↓" },
  { key: "score_asc", label: "Score ↑" },
];

export default async function CandidatesPage({
  searchParams,
}: {
  searchParams: Promise<{ status?: string; sort?: string }>;
}) {
  const sp = await searchParams;
  const h = await headers();
  const host = h.get("x-forwarded-host") ?? h.get("host") ?? "localhost:3000";
  const proto = h.get("x-forwarded-proto") ?? "http";
  const baseUrl = `${proto}://${host}`;
  const cookieHeader = h.get("cookie") ?? undefined;

  let rows: Row[] = [];
  let error: string | null = null;
  try {
    rows = await backend.listCandidates(
      { status: sp.status || undefined, sort: sp.sort || "created_desc" },
      { baseUrl, cookieHeader },
    );
  } catch (err) {
    error = (err as Error).message;
  }

  const metrics = computeMetrics(rows);

  return (
    <>
      {/* Metrics bento — three real numbers, no decorative placeholders. */}
      <section className="grid grid-cols-1 md:grid-cols-3 gap-8 mb-16">
        <MetricCard label="Total Candidates" value={metrics.total.toString()} accent />
        <MetricCard
          label="Manual Review"
          value={metrics.manualReview.toString()}
          hint="Requires action"
        />
        <MetricCard
          label="Avg. Score"
          value={metrics.avgScore != null ? metrics.avgScore.toFixed(1) : "—"}
          hint="Across scored candidates"
        />
      </section>

      <section className="bg-surface-container-low rounded-[2rem] p-4">
        <div className="px-8 py-6 flex justify-between items-end">
          <div>
            <h2 className="text-3xl font-headline font-extrabold tracking-tight">
              Candidate Pipeline
            </h2>
            <p className="text-sm opacity-60 mt-1">
              Intelligence-driven selection
            </p>
          </div>

          <div className="flex gap-3">
            <FilterTabs current={sp.status ?? ""} currentSort={sp.sort ?? ""} />
            <SortSelect current={sp.sort ?? ""} currentStatus={sp.status ?? ""} />
          </div>
        </div>

        {error ? (
          <div className="px-8 py-16 text-center text-on-surface-variant">
            <p className="font-headline font-bold text-lg">Backend unavailable</p>
            <p className="text-sm mt-2">{error}</p>
          </div>
        ) : rows.length === 0 ? (
          <div className="px-8 py-16 text-center text-on-surface-variant">
            <p className="font-headline font-bold text-lg">No candidates yet</p>
            <p className="text-sm mt-2">
              Poll the inbox or wait for the scheduler to pick up new applications.
            </p>
          </div>
        ) : (
          <div className="flex flex-col gap-4 mt-2">
            {rows.map((row) => (
              <CandidateRow key={row.id} row={row} />
            ))}
          </div>
        )}
      </section>
    </>
  );
}

function computeMetrics(rows: Row[]) {
  const scored = rows.filter((r) => r.overall_score != null);
  const avg =
    scored.length > 0
      ? scored.reduce((sum, r) => sum + (r.overall_score ?? 0), 0) /
        scored.length /
        10
      : null;
  return {
    total: rows.length,
    manualReview: rows.filter((r) => r.status === "manual_review").length,
    avgScore: avg,
  };
}

function MetricCard({
  label,
  value,
  hint,
  accent = false,
}: {
  label: string;
  value: string;
  hint?: string;
  accent?: boolean;
}) {
  return (
    <div className="bg-surface-container-lowest p-8 rounded-[2rem] shadow-editorial-soft flex flex-col gap-2">
      <span className="text-xs font-bold uppercase tracking-widest opacity-50 font-label">
        {label}
      </span>
      <span
        className={`text-5xl font-headline font-black ${accent ? "text-primary" : "text-on-surface"}`}
      >
        {value}
      </span>
      {hint && (
        <span className="text-[10px] opacity-40 font-bold uppercase mt-4">{hint}</span>
      )}
    </div>
  );
}

function FilterTabs({ current, currentSort }: { current: string; currentSort: string }) {
  return (
    <div className="flex gap-2 flex-wrap">
      {FILTERS.map((f) => {
        const qs = new URLSearchParams();
        if (f.key) qs.set("status", f.key);
        if (currentSort) qs.set("sort", currentSort);
        const href = `/candidates${qs.toString() ? `?${qs}` : ""}`;
        const active = current === f.key;
        return (
          <Link
            key={f.key || "all"}
            href={href}
            className={
              active
                ? "px-4 py-2 rounded-xl text-xs font-bold bg-primary text-on-primary"
                : "px-4 py-2 rounded-xl text-xs font-bold bg-surface-container-lowest text-on-surface-variant hover:text-primary"
            }
          >
            {f.label}
          </Link>
        );
      })}
    </div>
  );
}

function SortSelect({
  current,
  currentStatus,
}: {
  current: string;
  currentStatus: string;
}) {
  return (
    <div className="flex gap-1">
      {SORTS.map((s) => {
        const qs = new URLSearchParams();
        if (currentStatus) qs.set("status", currentStatus);
        qs.set("sort", s.key);
        const href = `/candidates?${qs.toString()}`;
        const active = (current || "created_desc") === s.key;
        return (
          <Link
            key={s.key}
            href={href}
            className={
              active
                ? "px-3 py-2 rounded-xl text-xs font-bold bg-primary/10 text-primary"
                : "px-3 py-2 rounded-xl text-xs font-bold text-on-surface-variant hover:text-primary"
            }
          >
            {s.label}
          </Link>
        );
      })}
    </div>
  );
}
