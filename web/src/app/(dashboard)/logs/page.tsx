import { headers } from "next/headers";
import Link from "next/link";

import { backend } from "@/lib/backend";
import type { LogEntryWithCandidate } from "@/lib/types";

export const dynamic = "force-dynamic";

const LEVEL_FILTERS = [
  { key: "", label: "All" },
  { key: "info", label: "Info" },
  { key: "warn", label: "Warnings" },
  { key: "error", label: "Errors" },
];

const PAGE_SIZE = 100;

export default async function LogsPage({
  searchParams,
}: {
  searchParams: Promise<{ level?: string; step?: string; page?: string }>;
}) {
  const sp = await searchParams;
  const h = await headers();
  const host = h.get("x-forwarded-host") ?? h.get("host") ?? "localhost:3000";
  const proto = h.get("x-forwarded-proto") ?? "http";
  const baseUrl = `${proto}://${host}`;
  const cookieHeader = h.get("cookie") ?? undefined;

  const page = Math.max(1, parseInt(sp.page ?? "1", 10) || 1);
  const offset = (page - 1) * PAGE_SIZE;

  let logs: LogEntryWithCandidate[] = [];
  let error: string | null = null;
  try {
    logs = await backend.getLogs(
      {
        level: sp.level || undefined,
        step: sp.step || undefined,
        limit: PAGE_SIZE,
        offset,
      },
      { baseUrl, cookieHeader },
    );
  } catch (err) {
    error = (err as Error).message;
  }

  const errorCount = logs.filter((l) => l.level === "error").length;
  const warnCount = logs.filter((l) => l.level === "warn").length;
  const steps = [...new Set(logs.map((l) => l.step))].sort();

  return (
    <>
      <header className="mb-12">
        <h1 className="font-headline text-5xl font-black tracking-tighter mb-2 italic">
          System Logs
        </h1>
        <p className="text-on-surface-variant max-w-xl font-label text-sm uppercase tracking-widest opacity-70">
          Pipeline processing timeline across all candidates
        </p>
      </header>

      {/* Metrics */}
      <section className="grid grid-cols-1 md:grid-cols-3 gap-8 mb-16">
        <MetricCard label="Logs Shown" value={logs.length.toString()} accent />
        <MetricCard label="Errors" value={errorCount.toString()} hint="In current view" />
        <MetricCard label="Warnings" value={warnCount.toString()} hint="In current view" />
      </section>

      {/* Filters */}
      <section className="bg-surface-container-low rounded-[2rem] p-4">
        <div className="px-8 py-6 flex flex-wrap justify-between items-end gap-4">
          <div>
            <h2 className="text-3xl font-headline font-extrabold tracking-tight">
              Log Stream
            </h2>
            <p className="text-sm opacity-60 mt-1">Newest first</p>
          </div>
          <div className="flex gap-3 flex-wrap">
            <LevelTabs current={sp.level ?? ""} currentStep={sp.step ?? ""} />
            {steps.length > 0 && (
              <StepFilter current={sp.step ?? ""} currentLevel={sp.level ?? ""} steps={steps} />
            )}
          </div>
        </div>

        {error ? (
          <div className="px-8 py-16 text-center text-on-surface-variant">
            <p className="font-headline font-bold text-lg">Backend unavailable</p>
            <p className="text-sm mt-2">{error}</p>
          </div>
        ) : logs.length === 0 ? (
          <div className="px-8 py-16 text-center text-on-surface-variant">
            <p className="font-headline font-bold text-lg">No logs found</p>
            <p className="text-sm mt-2">
              Processing logs will appear here once candidates are evaluated.
            </p>
          </div>
        ) : (
          <>
            <div className="flex flex-col gap-0 mt-2">
              {groupLogsByCandidate(logs).map((group) => (
                <div key={group.key} className="mb-2">
                  <div className="px-8 py-3 flex items-center gap-3 bg-surface-container rounded-xl">
                    {group.candidateId ? (
                      <Link
                        href={`/candidates/${group.candidateId}`}
                        className="text-primary hover:underline font-headline font-bold text-sm"
                      >
                        {group.candidateName || group.candidateEmail || `#${group.candidateId}`}
                      </Link>
                    ) : (
                      <span className="font-headline font-bold text-sm opacity-40">System</span>
                    )}
                    <span className="text-[10px] opacity-40 font-bold uppercase">
                      {group.logs.length} log{group.logs.length !== 1 ? "s" : ""}
                    </span>
                  </div>
                  <div className="flex flex-col gap-1 mt-1">
                    {group.logs.map((log) => (
                      <LogRow key={log.id} log={log} />
                    ))}
                  </div>
                </div>
              ))}
            </div>

            {/* Pagination */}
            <div className="flex justify-center gap-4 px-8 py-6">
              {page > 1 && (
                <Link
                  href={buildUrl({ ...sp, page: (page - 1).toString() })}
                  className="px-4 py-2 rounded-full bg-surface-container-lowest text-sm font-bold hover:text-primary transition-colors"
                >
                  Previous
                </Link>
              )}
              <span className="px-4 py-2 text-sm opacity-50">Page {page}</span>
              {logs.length === PAGE_SIZE && (
                <Link
                  href={buildUrl({ ...sp, page: (page + 1).toString() })}
                  className="px-4 py-2 rounded-full bg-surface-container-lowest text-sm font-bold hover:text-primary transition-colors"
                >
                  Next
                </Link>
              )}
            </div>
          </>
        )}
      </section>
    </>
  );
}

interface LogGroup {
  key: string;
  candidateId: number | null;
  candidateName: string | null;
  candidateEmail: string | null;
  logs: LogEntryWithCandidate[];
}

function groupLogsByCandidate(logs: LogEntryWithCandidate[]): LogGroup[] {
  const groups: LogGroup[] = [];
  let current: LogGroup | null = null;
  for (const log of logs) {
    const id = log.candidate_id;
    if (!current || current.candidateId !== id) {
      current = {
        key: id != null ? `c-${id}` : `sys-${groups.length}`,
        candidateId: id,
        candidateName: log.candidate_name,
        candidateEmail: log.candidate_email,
        logs: [],
      };
      groups.push(current);
    }
    current.logs.push(log);
  }
  return groups;
}

function buildUrl(params: Record<string, string | undefined>) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v) qs.set(k, v);
  }
  const suffix = qs.toString() ? `?${qs}` : "";
  return `/logs${suffix}`;
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

function LevelTabs({ current, currentStep }: { current: string; currentStep: string }) {
  return (
    <div className="flex gap-2">
      {LEVEL_FILTERS.map((f) => {
        const active = current === f.key;
        const params: Record<string, string> = {};
        if (f.key) params.level = f.key;
        if (currentStep) params.step = currentStep;
        return (
          <Link
            key={f.key}
            href={buildUrl(params)}
            className={`px-4 py-2 rounded-full text-xs font-bold uppercase tracking-wider transition-colors ${
              active
                ? "bg-primary text-on-primary"
                : "bg-surface-container-lowest text-on-surface-variant hover:text-primary"
            }`}
          >
            {f.label}
          </Link>
        );
      })}
    </div>
  );
}

function StepFilter({
  current,
  currentLevel,
  steps,
}: {
  current: string;
  currentLevel: string;
  steps: string[];
}) {
  return (
    <div className="flex gap-2 items-center">
      <span className="text-xs opacity-40 font-bold uppercase">Step:</span>
      <Link
        href={buildUrl({ level: currentLevel || undefined })}
        className={`px-3 py-1.5 rounded-full text-xs font-bold transition-colors ${
          !current
            ? "bg-primary text-on-primary"
            : "bg-surface-container-lowest text-on-surface-variant hover:text-primary"
        }`}
      >
        All
      </Link>
      {steps.map((s) => (
        <Link
          key={s}
          href={buildUrl({ step: s, level: currentLevel || undefined })}
          className={`px-3 py-1.5 rounded-full text-xs font-bold transition-colors ${
            current === s
              ? "bg-primary text-on-primary"
              : "bg-surface-container-lowest text-on-surface-variant hover:text-primary"
          }`}
        >
          {s}
        </Link>
      ))}
    </div>
  );
}

function LogRow({ log }: { log: LogEntryWithCandidate }) {
  const levelColor =
    log.level === "error"
      ? "text-error"
      : log.level === "warn"
        ? "text-tertiary"
        : "text-on-surface-variant";

  const levelBg =
    log.level === "error"
      ? "bg-error/5"
      : log.level === "warn"
        ? "bg-tertiary/5"
        : "";

  const ts = new Date(log.created_at);
  const time = ts.toLocaleTimeString("en-US", { hour12: false });
  const date = ts.toLocaleDateString("en-US", { month: "short", day: "numeric" });

  return (
    <div
      className={`px-8 py-3 flex items-start gap-4 text-sm rounded-xl hover:bg-surface-container-lowest/60 transition-colors ${levelBg}`}
    >
      {/* Timestamp */}
      <span className="text-[11px] font-mono opacity-40 w-28 flex-shrink-0 pt-0.5">
        {date} {time}
      </span>

      {/* Step badge */}
      <span className="text-[10px] uppercase font-bold opacity-60 bg-surface-container px-2 py-0.5 rounded-md w-40 flex-shrink-0 truncate">
        {log.step}
      </span>

      {/* Level */}
      <span className={`text-[10px] uppercase font-black w-12 flex-shrink-0 ${levelColor}`}>
        {log.level}
      </span>

      {/* Message */}
      <span className={`flex-1 ${levelColor}`}>{log.message}</span>

      {/* Meta (collapsed preview) */}
      {log.meta && Object.keys(log.meta).length > 0 && (
        <details className="flex-shrink-0">
          <summary className="text-[10px] uppercase font-bold opacity-30 cursor-pointer hover:opacity-60">
            meta
          </summary>
          <pre className="mt-2 text-[11px] font-mono bg-surface-container p-3 rounded-lg max-w-md overflow-auto max-h-48 whitespace-pre-wrap">
            {JSON.stringify(log.meta, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
}
