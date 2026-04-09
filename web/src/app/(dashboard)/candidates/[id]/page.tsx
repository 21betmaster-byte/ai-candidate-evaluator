import { headers } from "next/headers";
import Link from "next/link";
import { notFound } from "next/navigation";

import DecisionButtons from "@/components/DecisionButtons";
import { backend, BackendError } from "@/lib/backend";
import type { CandidateDetail, EmailHistoryEntry, ScoreEntry } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function CandidateDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id: idRaw } = await params;
  const id = Number(idRaw);
  if (!Number.isFinite(id)) notFound();

  const h = await headers();
  const host = h.get("x-forwarded-host") ?? h.get("host") ?? "localhost:3000";
  const proto = h.get("x-forwarded-proto") ?? "http";
  const baseUrl = `${proto}://${host}`;
  const cookieHeader = h.get("cookie") ?? undefined;

  let candidate: CandidateDetail;
  try {
    candidate = await backend.getCandidate(id, { baseUrl, cookieHeader });
  } catch (err) {
    if (err instanceof BackendError && err.status === 404) notFound();
    throw err;
  }

  const ev = candidate.current_evaluation;
  const profile = (ev?.structured_profile ?? null) as ProfileShape | null;
  const displayName = candidate.name ?? profile?.name ?? candidate.email.split("@")[0];
  const scores = ev?.scores ?? {};
  const overall = ev?.overall_score != null ? (ev.overall_score / 10).toFixed(1) : "—";

  return (
    <div className="max-w-7xl mx-auto">
      <nav className="flex items-center gap-2 mb-8 opacity-60">
        <Link href="/candidates" className="text-xs font-label font-semibold tracking-wider hover:text-primary">
          CANDIDATES
        </Link>
        <span className="material-symbols-outlined text-sm">chevron_right</span>
        <span className="text-xs font-label font-semibold tracking-wider text-primary uppercase">
          {displayName}
        </span>
      </nav>

      <div className="flex justify-between items-end mb-16">
        <div>
          <h2 className="text-6xl font-black font-headline tracking-tighter text-on-surface mb-2">
            {displayName}
          </h2>
          <p className="text-xl font-body text-primary font-semibold">
            {profile?.headline ?? profile?.current_role ?? candidate.email}
          </p>
          <p className="text-xs opacity-60 mt-2 uppercase tracking-widest font-bold">
            Status · {candidate.status.replace("_", " ")}
          </p>
        </div>
        <DecisionButtons candidateId={candidate.id} status={candidate.status} />
      </div>

      {candidate.review_source === "intake_review" && (
        <IntakeReviewBanner reason={candidate.review_reason} />
      )}

      {ev == null ? (
        <div className="space-y-8">
          <div className="bg-surface-container-lowest p-10 rounded-xl shadow-editorial-soft">
            <p className="font-headline text-xl font-bold mb-2">Awaiting evaluation</p>
            <p className="text-sm opacity-60">
              The candidate is still moving through the pipeline. Check back after
              the next poll completes.
            </p>
          </div>
          <EmailHistory entries={candidate.email_history} />
          <ProcessingTimeline logs={candidate.logs} />
        </div>
      ) : (
        <div className="grid grid-cols-12 gap-8">
          <div className="col-span-12 lg:col-span-8 space-y-8">
            <IdentityCard candidate={candidate} profile={profile} />
            {Object.keys(scores).length > 0 && (
              <VerdictCard reason={ev.decision_reason} tier={ev.tier} overall={overall} />
            )}
            <ProfileCard profile={profile} />
            <EmailHistory entries={candidate.email_history} />
            <ProcessingTimeline logs={candidate.logs} />
          </div>

          <div className="col-span-12 lg:col-span-4 space-y-8">
            {Object.keys(scores).length > 0 && <RubricCard scores={scores} />}
            <SignalsCard ev={ev} profile={profile} />
          </div>
        </div>
      )}
    </div>
  );
}

function IntakeReviewBanner({ reason }: { reason: string | null }) {
  return (
    <div className="bg-tertiary-container/40 border-l-4 border-tertiary p-6 rounded-xl mb-8">
      <div className="flex items-start gap-3">
        <span className="material-symbols-outlined text-tertiary mt-0.5">flag</span>
        <div>
          <p className="font-headline text-base font-bold uppercase tracking-wider">
            Flagged for human review
          </p>
          <p className="text-sm opacity-80 mt-1 leading-relaxed">
            {reason ||
              "This application contained context that didn't fit our standard checklist. A human should take a look before deciding."}
          </p>
        </div>
      </div>
    </div>
  );
}

function EmailHistory({ entries }: { entries: EmailHistoryEntry[] }) {
  if (!entries.length) return null;
  return (
    <div className="bg-surface-container-lowest p-8 rounded-xl">
      <h3 className="font-headline text-xl font-bold mb-6">Email History</h3>
      <div className="space-y-3">
        {entries.map((e) => (
          <details
            key={e.id}
            className="group border border-outline-variant/30 rounded-lg overflow-hidden"
          >
            <summary className="cursor-pointer list-none flex items-center gap-3 px-4 py-3 hover:bg-surface-container-low">
              <span
                className={`text-[10px] font-label font-bold uppercase tracking-widest px-2 py-0.5 rounded ${
                  e.direction === "in"
                    ? "bg-primary/10 text-primary"
                    : "bg-secondary-container text-on-secondary-container"
                }`}
              >
                {e.direction === "in" ? "Received" : "Sent"}
              </span>
              <span className="font-semibold text-sm flex-1 truncate">
                {e.subject || "(no subject)"}
              </span>
              <span className="text-xs opacity-50 flex-shrink-0">
                {new Date(e.created_at).toLocaleString()}
              </span>
              <span className="material-symbols-outlined text-base opacity-40 group-open:rotate-180 transition-transform">
                expand_more
              </span>
            </summary>
            <div className="px-4 pb-4 pt-2 border-t border-outline-variant/20">
              <p className="text-[11px] opacity-50 mb-3">
                {e.direction === "in" ? "From" : "To"}: {e.sender || "—"}
                {e.template_used ? ` · template: ${e.template_used}` : ""}
                {e.classification ? ` · classified: ${e.classification}` : ""}
              </p>
              {e.body ? (
                <pre className="text-sm whitespace-pre-wrap font-body leading-relaxed">
                  {e.body}
                </pre>
              ) : (
                <p className="text-xs italic opacity-60">
                  Couldn't load this message body ({e.body_error || "unknown error"}).
                </p>
              )}
            </div>
          </details>
        ))}
      </div>
    </div>
  );
}

// ---------- sub components ----------

type ProfileShape = {
  name?: string;
  headline?: string;
  current_role?: string;
  years_of_experience?: number | null;
  work_experience?: {
    company: string;
    title: string;
    duration: string;
    highlights: string[];
  }[];
  shipped_products?: { name: string; description: string }[];
  technical_skills?: {
    from_resume?: string[];
    from_github_languages?: string[];
    from_github_manifests?: string[];
  };
  github_signal?: {
    active?: boolean;
    primary_languages?: string[];
    activity_summary?: string;
    total_public_repos?: number | null;
  };
  portfolio_signal?: {
    has_real_projects?: boolean;
    project_count?: number;
    has_live_demos?: boolean;
    live_demo_count?: number;
  };
};

function IdentityCard({
  candidate,
  profile,
}: {
  candidate: CandidateDetail;
  profile: ProfileShape | null;
}) {
  return (
    <div className="bg-surface-container-lowest p-10 rounded-xl">
      <div className="grid grid-cols-2 gap-y-6">
        <Field label="Current Role" value={profile?.current_role ?? "—"} />
        <Field
          label="Experience"
          value={
            profile?.years_of_experience != null
              ? `${profile.years_of_experience} years`
              : "—"
          }
        />
        <Field label="Email" value={candidate.email} full />
      </div>
    </div>
  );
}

function Field({ label, value, full = false }: { label: string; value: string; full?: boolean }) {
  return (
    <div className={full ? "col-span-2" : ""}>
      <p className="text-[10px] font-label font-bold text-outline opacity-60 uppercase tracking-[0.2em] mb-1">
        {label}
      </p>
      <p className="font-body font-semibold text-on-surface break-words">{value}</p>
    </div>
  );
}

function VerdictCard({
  reason,
  tier,
  overall,
}: {
  reason: string | null;
  tier: string | null;
  overall: string;
}) {
  return (
    <div className="bg-surface-container-low p-10 rounded-xl relative overflow-hidden">
      <div className="absolute top-0 right-0 w-32 h-32 bg-primary/5 rounded-full -mr-16 -mt-16 blur-3xl" />
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <span className="material-symbols-outlined text-primary filled">auto_awesome</span>
          <h3 className="font-headline text-lg font-bold">Curator's Verdict</h3>
        </div>
        <div className="flex items-baseline gap-2">
          <span className="font-headline text-4xl font-black text-primary">{overall}</span>
          <span className="text-xs font-bold opacity-40 uppercase">Overall</span>
        </div>
      </div>
      <p className="text-lg leading-relaxed font-body text-on-surface/90 italic">
        “{reason || "No decision reason recorded."}”
      </p>
      {tier && (
        <div className="mt-8">
          <span className="bg-secondary-container text-on-secondary-container px-4 py-1.5 rounded-full text-xs font-bold font-label uppercase">
            {tier.replace("_", " ")}
          </span>
        </div>
      )}
    </div>
  );
}

function ProfileCard({ profile }: { profile: ProfileShape | null }) {
  if (!profile) return null;
  const products = profile.shipped_products ?? [];
  const work = profile.work_experience ?? [];
  return (
    <div className="space-y-8">
      {products.length > 0 && (
        <div className="bg-surface-container-lowest p-8 rounded-xl">
          <h3 className="font-headline text-xl font-bold mb-6">Shipped Products</h3>
          <div className="space-y-4">
            {products.map((p, i) => (
              <div key={i} className="border-b border-outline-variant/20 last:border-0 pb-4 last:pb-0">
                <p className="font-headline font-bold text-base">{p.name}</p>
                <p className="text-sm opacity-70 mt-1">{p.description}</p>
              </div>
            ))}
          </div>
        </div>
      )}
      {work.length > 0 && (
        <div className="bg-surface-container-lowest p-8 rounded-xl">
          <h3 className="font-headline text-xl font-bold mb-6">Experience</h3>
          <div className="space-y-6">
            {work.map((w, i) => (
              <div key={i}>
                <div className="flex justify-between items-baseline">
                  <p className="font-headline font-bold">
                    {w.title} · {w.company}
                  </p>
                  <p className="text-xs opacity-60">{w.duration}</p>
                </div>
                {w.highlights?.length ? (
                  <ul className="mt-2 space-y-1 text-sm opacity-80 list-disc list-inside">
                    {w.highlights.slice(0, 4).map((h, j) => (
                      <li key={j}>{h}</li>
                    ))}
                  </ul>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function RubricCard({ scores }: { scores: Record<string, ScoreEntry> }) {
  const entries = Object.entries(scores);
  return (
    <div className="bg-surface-container-lowest p-8 rounded-xl shadow-editorial-soft">
      <h3 className="font-headline text-xl font-bold mb-8">Rubric Performance</h3>
      {entries.length === 0 ? (
        <p className="text-sm opacity-60">No scores recorded.</p>
      ) : (
        <div className="space-y-8">
          {entries.map(([key, { score, reasoning }]) => (
            <div key={key}>
              <div className="flex justify-between items-end mb-2">
                <span className="text-xs font-label font-bold uppercase tracking-wider opacity-60">
                  {key.replace(/_/g, " ")}
                </span>
                <span className="text-2xl font-headline font-black text-primary">
                  {(score / 10).toFixed(1)}
                </span>
              </div>
              <div className="h-1.5 w-full bg-surface-container rounded-full overflow-hidden">
                <div className="h-full bg-primary" style={{ width: `${score}%` }} />
              </div>
              {reasoning && (
                <p className="text-xs opacity-70 mt-2 leading-relaxed">{reasoning}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function SignalsCard({
  ev,
  profile,
}: {
  ev: NonNullable<CandidateDetail["current_evaluation"]>;
  profile: ProfileShape | null;
}) {
  return (
    <div className="bg-surface-container-lowest p-8 rounded-xl">
      <h3 className="font-headline text-lg font-bold mb-6">Signals</h3>
      <dl className="space-y-4 text-sm">
        {ev.github_url && (
          <SignalRow label="GitHub">
            <a href={ev.github_url} target="_blank" rel="noreferrer" className="text-primary hover:underline">
              {shortUrl(ev.github_url)}
            </a>
          </SignalRow>
        )}
        {ev.portfolio_url && (
          <SignalRow label="Portfolio">
            <a href={ev.portfolio_url} target="_blank" rel="noreferrer" className="text-primary hover:underline">
              {shortUrl(ev.portfolio_url)}
            </a>
          </SignalRow>
        )}
        {ev.resume_filename && <SignalRow label="Resume">{ev.resume_filename}</SignalRow>}
        {profile?.github_signal?.activity_summary && (
          <SignalRow label="GH Activity">{profile.github_signal.activity_summary}</SignalRow>
        )}
        {profile?.portfolio_signal?.live_demo_count != null && (
          <SignalRow label="Live Demos">{profile.portfolio_signal.live_demo_count}</SignalRow>
        )}
      </dl>
    </div>
  );
}

function SignalRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-[10px] font-label font-bold uppercase tracking-widest opacity-50">
        {label}
      </dt>
      <dd className="font-semibold mt-1 break-words">{children}</dd>
    </div>
  );
}

function shortUrl(u: string) {
  try {
    const p = new URL(u);
    return `${p.hostname}${p.pathname.length > 1 ? p.pathname : ""}`;
  } catch {
    return u;
  }
}

function ProcessingTimeline({ logs }: { logs: CandidateDetail["logs"] }) {
  if (!logs.length) return null;
  return (
    <div className="bg-surface-container-lowest p-8 rounded-xl">
      <h3 className="font-headline text-lg font-bold mb-4">Processing Timeline</h3>
      <ol className="space-y-3 text-sm">
        {logs.map((l) => {
          const color =
            l.level === "error"
              ? "text-error"
              : l.level === "warn"
                ? "text-tertiary"
                : "text-on-surface-variant";
          return (
            <li key={l.id} className="flex items-start gap-3">
              <span className="text-[10px] uppercase font-bold opacity-40 w-20 flex-shrink-0 pt-0.5">
                {l.step}
              </span>
              <span className={color}>{l.message}</span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
