import Link from "next/link";
import type { CandidateRow as Row } from "@/lib/types";

/**
 * Single row in the candidates hub, styled after the stitch mock.
 * - Score is rendered on the mock's 0–9.9 scale (backend stores 0–100).
 * - Status pill color varies by tier.
 * - The whole row links to /candidates/[id].
 */
const STATUS_META: Record<
  Row["status"],
  { label: string; badge: string; emphasise: boolean }
> = {
  manual_review: {
    label: "Manual Review",
    badge: "bg-primary-fixed text-on-primary-fixed-variant",
    emphasise: true,
  },
  auto_pass: {
    label: "Auto-Pass",
    badge: "bg-green-100 text-green-800",
    emphasise: false,
  },
  passed_manual: {
    label: "Passed",
    badge: "bg-green-100 text-green-800",
    emphasise: false,
  },
  auto_fail: {
    label: "Auto-Fail",
    badge: "bg-error-container text-on-error-container",
    emphasise: false,
  },
  failed_manual: {
    label: "Failed",
    badge: "bg-error-container text-on-error-container",
    emphasise: false,
  },
  incomplete: {
    label: "Incomplete",
    badge: "bg-secondary-container text-on-secondary-container",
    emphasise: false,
  },
  pending: {
    label: "Pending",
    badge: "bg-surface-container-high text-on-surface/70",
    emphasise: false,
  },
  processing_error: {
    label: "Error",
    badge: "bg-error-container text-on-error-container",
    emphasise: false,
  },
};

function initialsOf(name: string | null, email: string) {
  const src = (name ?? email.split("@")[0]).trim();
  const parts = src.split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "??";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

export default function CandidateRow({ row }: { row: Row }) {
  const meta = STATUS_META[row.status];
  const score =
    row.overall_score != null ? Math.round(row.overall_score).toString() : "—";
  const displayName = row.name ?? row.email.split("@")[0];
  const emphasiseClasses = meta.emphasise
    ? "border-l-4 border-primary shadow-sm"
    : "opacity-80 hover:opacity-100";
  const created = new Date(row.created_at).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });

  return (
    <Link
      href={`/candidates/${row.id}`}
      className={`bg-surface-container-lowest rounded-2xl p-6 flex items-center justify-between hover:translate-x-1 transition-transform ${emphasiseClasses}`}
    >
      <div className="flex items-center gap-6 w-1/4 min-w-0">
        <div className="w-14 h-14 rounded-full bg-primary/10 text-primary flex items-center justify-center font-headline font-black text-lg flex-shrink-0">
          {initialsOf(row.name, row.email)}
        </div>
        <div className="min-w-0">
          <p className="font-headline font-bold text-lg truncate">{displayName}</p>
          <p className="text-xs opacity-50 font-medium truncate">{row.email}</p>
        </div>
      </div>
      <div className="w-1/6 flex flex-col items-center">
        <span className={`text-2xl font-headline font-black ${meta.emphasise ? "text-primary" : "text-on-surface"}`}>
          {score}
        </span>
        <span className="text-[10px] uppercase font-bold opacity-40">Intelligence Score</span>
      </div>
      <div className="w-1/6 flex justify-center">
        <span
          className={`px-4 py-1 rounded-full text-[10px] font-black uppercase tracking-widest ${meta.badge}`}
        >
          {meta.label}
        </span>
      </div>
      <div className="w-1/6 text-center">
        <p className="text-sm font-semibold">{created}</p>
        <p className="text-[10px] opacity-40 font-bold uppercase">Date Indexed</p>
      </div>
      <div className="w-1/6 flex justify-end">
        <span className="px-8 py-3 rounded-full font-headline font-black text-sm bg-surface-container text-on-surface-variant group-hover:bg-primary group-hover:text-on-primary">
          Review
        </span>
      </div>
    </Link>
  );
}
