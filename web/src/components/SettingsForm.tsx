"use client";
/**
 * Settings page — the central piece. Hiring managers author the rubric
 * here: name (key), free-text description fed to Opus, and a weight.
 * Weights must sum to 100. Also exposes tier thresholds, polling cadence,
 * company name, pass/next-steps text, and reminder cadence.
 *
 * Contract: anything valid here gets PUT to /api/backend/settings. The
 * backend schema rejects invalid payloads (unique keys, weights sum to 100,
 * ordered thresholds) so we mirror those checks client-side for fast
 * feedback but treat the server's error as authoritative.
 */
import { useMemo, useState, useTransition } from "react";
import { useRouter } from "next/navigation";

import { backend, BackendError } from "@/lib/backend";
import type { RubricDimension, SettingsModel } from "@/lib/types";

const KEY_RE = /^[a-z0-9][a-z0-9_]{0,63}$/;

function slugify(label: string): string {
  return label
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 64);
}

function nextBlankDimension(existing: RubricDimension[]): RubricDimension {
  // Give new rows a zero weight so total doesn't jump unexpectedly.
  // Hiring manager then redistributes manually.
  return { key: "", description: "", weight: 0 };
}

export default function SettingsForm({ initial }: { initial: SettingsModel }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [rubric, setRubric] = useState<RubricDimension[]>(initial.rubric);
  const [polling, setPolling] = useState(initial.polling_minutes);
  const [autoFail, setAutoFail] = useState(initial.tier_thresholds.auto_fail_ceiling);
  const [manualReview, setManualReview] = useState(initial.tier_thresholds.manual_review_ceiling);
  const [autoPass, setAutoPass] = useState(initial.tier_thresholds.auto_pass_floor);
  const [companyName, setCompanyName] = useState(initial.company_name);

  const [reminderHours, setReminderHours] = useState(initial.reminder_hours);
  const [incompleteExpiryDays, setIncompleteExpiryDays] = useState(initial.incomplete_expiry_days);

  const weightTotal = useMemo(
    () => rubric.reduce((s, d) => s + (Number.isFinite(d.weight) ? d.weight : 0), 0),
    [rubric],
  );

  const clientErrors = useMemo(() => {
    const errs: string[] = [];
    if (rubric.length === 0) errs.push("Add at least one rubric dimension.");
    const seen = new Set<string>();
    for (const d of rubric) {
      if (!d.key) errs.push("Every dimension needs a key.");
      else if (!KEY_RE.test(d.key))
        errs.push(`"${d.key}" is not a valid key (lowercase letters, digits, underscores).`);
      else if (seen.has(d.key)) errs.push(`Duplicate key: ${d.key}.`);
      seen.add(d.key);
      if (!d.description.trim()) errs.push(`"${d.key || "(unnamed)"}" needs a description.`);
    }
    if (weightTotal !== 100) errs.push(`Weights must sum to 100 (currently ${weightTotal}).`);
    if (!(autoFail < manualReview && manualReview < autoPass)) {
      errs.push("Thresholds must be ordered: auto-fail < manual-review < auto-pass.");
    }
    // Dedupe repeated messages.
    return Array.from(new Set(errs));
  }, [rubric, weightTotal, autoFail, manualReview, autoPass]);

  const canSave = clientErrors.length === 0;

  function updateDim(i: number, patch: Partial<RubricDimension>) {
    setRubric((prev) => prev.map((d, idx) => (idx === i ? { ...d, ...patch } : d)));
  }

  function addDim() {
    setRubric((prev) => [...prev, nextBlankDimension(prev)]);
  }

  function removeDim(i: number) {
    setRubric((prev) => prev.filter((_, idx) => idx !== i));
  }

  function distributeEvenly() {
    if (rubric.length === 0) return;
    const base = Math.floor(100 / rubric.length);
    const remainder = 100 - base * rubric.length;
    setRubric((prev) =>
      prev.map((d, i) => ({ ...d, weight: base + (i < remainder ? 1 : 0) })),
    );
  }

  function save() {
    setError(null);
    setSaved(false);
    const payload: SettingsModel = {
      polling_minutes: polling,
      rubric: rubric.map((d) => ({
        key: d.key.trim(),
        description: d.description.trim(),
        weight: d.weight,
      })),
      tier_thresholds: {
        auto_fail_ceiling: autoFail,
        manual_review_ceiling: manualReview,
        auto_pass_floor: autoPass,
      },

      reminder_hours: reminderHours,
      incomplete_expiry_days: incompleteExpiryDays,
      company_name: companyName.trim(),
    };
    startTransition(async () => {
      try {
        const updated = await backend.updateSettings(payload);
        setRubric(updated.rubric);
        setSaved(true);
        router.refresh();
      } catch (err) {
        setError(err instanceof BackendError ? err.message : "save failed");
      }
    });
  }

  return (
    <div className="grid grid-cols-12 gap-8">
      {/* Left column: rubric editor (the main event) */}
      <section className="col-span-12 lg:col-span-7 bg-surface-container-lowest p-8 lg:p-12 rounded-xl shadow-editorial-soft">
        <div className="flex items-center justify-between mb-10">
          <div className="flex items-center gap-3">
            <span className="material-symbols-outlined text-primary">psychology</span>
            <h2 className="font-headline text-2xl font-bold">Rubric</h2>
          </div>
          <div
            className={`px-4 py-1 rounded-full text-[10px] font-bold uppercase tracking-widest ${
              weightTotal === 100
                ? "bg-secondary-container text-on-secondary-container"
                : "bg-error-container text-on-error-container"
            }`}
          >
            {weightTotal === 100 ? "Balanced: 100%" : `Sum: ${weightTotal}%`}
          </div>
        </div>

        <p className="text-xs opacity-60 mb-8 leading-relaxed">
          These dimensions are sent verbatim to Opus. The description is the
          authoritative definition of what each dimension measures — write it
          as you would explain it to a new hiring manager on your team.
        </p>

        <div className="space-y-8">
          {rubric.map((dim, i) => (
            <DimensionRow
              key={i}
              dim={dim}
              onChange={(patch) => updateDim(i, patch)}
              onRemove={() => removeDim(i)}
              canRemove={rubric.length > 1}
            />
          ))}
        </div>

        <div className="mt-10 flex items-center gap-4">
          <button
            onClick={addDim}
            className="bg-surface-container text-on-surface px-6 py-3 rounded-full text-sm font-headline font-bold hover:bg-surface-container-high active:scale-95 transition-all"
          >
            + Add dimension
          </button>
          <button
            onClick={distributeEvenly}
            className="text-xs text-on-surface-variant hover:text-primary font-bold uppercase tracking-widest"
          >
            Distribute evenly
          </button>
        </div>

        {clientErrors.length > 0 && (
          <div className="mt-8 p-4 bg-error-container/60 rounded-lg">
            <ul className="text-xs text-on-error-container space-y-1 list-disc list-inside">
              {clientErrors.map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
          </div>
        )}
      </section>

      {/* Right column: thresholds, ingestion, messaging */}
      <div className="col-span-12 lg:col-span-5 space-y-8">
        <section className="bg-surface-container-lowest p-8 rounded-xl shadow-editorial-soft">
          <div className="flex items-center gap-3 mb-6">
            <span className="material-symbols-outlined text-primary">leaderboard</span>
            <h2 className="font-headline text-xl font-bold">Scoring Tiers</h2>
          </div>
          <div className="space-y-4 text-sm">
            <ThresholdRow
              label="Auto-Pass"
              hint="Directly moves to first interview"
              value={autoPass}
              onChange={setAutoPass}
              accent
            />
            <ThresholdRow
              label="Manual Review"
              hint="Requires editorial eyes"
              value={manualReview}
              onChange={setManualReview}
            />
            <ThresholdRow
              label="Auto-Fail"
              hint="Automated archive"
              value={autoFail}
              onChange={setAutoFail}
              error
            />
          </div>
          <p className="text-[10px] opacity-50 mt-4 leading-relaxed">
            Auto-fail &lt; manual-review &lt; auto-pass. Scores between
            auto-fail and manual-review land in manual review; scores at or
            above auto-pass are auto-passed.
          </p>
        </section>

        <section className="bg-surface-container-lowest p-8 rounded-xl shadow-editorial-soft">
          <div className="flex items-center gap-3 mb-6">
            <span className="material-symbols-outlined text-primary">move_to_inbox</span>
            <h2 className="font-headline text-xl font-bold">Ingestion</h2>
          </div>
          <div className="space-y-6">
            <LabeledInput label="Company Name" value={companyName} onChange={setCompanyName} />
            <div>
              <div className="flex justify-between items-center mb-2">
                <label className="text-[10px] font-label font-bold text-on-surface-variant uppercase tracking-widest">
                  Polling Frequency
                </label>
                <span className="text-xs font-headline font-bold text-primary">
                  Every {polling} min
                </span>
              </div>
              <input
                type="range"
                min={1}
                max={120}
                value={polling}
                onChange={(e) => setPolling(Number(e.target.value))}
              />
              <div className="flex justify-between text-[10px] font-medium opacity-50 mt-1">
                <span>1 min</span>
                <span>2 hours</span>
              </div>
            </div>
            <div>
              <div className="flex justify-between items-center mb-2">
                <label className="text-[10px] font-label font-bold text-on-surface-variant uppercase tracking-widest">
                  Reminder Cadence
                </label>
                <span className="text-xs font-headline font-bold text-primary">
                  {reminderHours} hours
                </span>
              </div>
              <input
                type="range"
                min={1}
                max={336}
                value={reminderHours}
                onChange={(e) => setReminderHours(Number(e.target.value))}
              />
            </div>
            <div>
              <div className="flex justify-between items-center mb-2">
                <label className="text-[10px] font-label font-bold text-on-surface-variant uppercase tracking-widest">
                  Incomplete Expiry
                </label>
                <span className="text-xs font-headline font-bold text-primary">
                  {incompleteExpiryDays} {incompleteExpiryDays === 1 ? "day" : "days"}
                </span>
              </div>
              <input
                type="range"
                min={1}
                max={30}
                value={incompleteExpiryDays}
                onChange={(e) => setIncompleteExpiryDays(Number(e.target.value))}
              />
              <div className="flex justify-between text-[10px] font-medium opacity-50 mt-1">
                <span>1 day</span>
                <span>30 days</span>
              </div>
            </div>
          </div>
        </section>

      </div>

      {/* Full-width footer actions */}
      <div className="col-span-12 flex items-center justify-end gap-6 pt-4">
        {saved && (
          <span className="text-xs font-bold uppercase tracking-widest text-green-700">
            Saved
          </span>
        )}
        {error && <span className="text-xs text-error">{error}</span>}
        <button
          onClick={save}
          disabled={!canSave || pending}
          className="bg-gradient-to-br from-primary to-primary/80 px-8 py-4 rounded-full text-on-primary font-headline font-black shadow-lg shadow-primary/20 hover:scale-105 active:scale-95 transition-all disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:scale-100"
        >
          {pending ? "Saving…" : "Save Settings"}
        </button>
      </div>
    </div>
  );
}

// ---------- sub components ----------

function DimensionRow({
  dim,
  onChange,
  onRemove,
  canRemove,
}: {
  dim: RubricDimension;
  onChange: (patch: Partial<RubricDimension>) => void;
  onRemove: () => void;
  canRemove: boolean;
}) {
  // Track whether the user has manually edited the key. If not, auto-derive
  // it from the "name" field so hiring managers don't have to think about
  // slugs unless they want to.
  const [keyTouched, setKeyTouched] = useState(Boolean(dim.key));
  const [label, setLabel] = useState(() => dim.key.replace(/_/g, " "));

  return (
    <div className="group border-t border-outline-variant/20 pt-6 first:border-0 first:pt-0">
      <div className="flex items-start gap-4">
        <div className="flex-1 space-y-3">
          <input
            type="text"
            placeholder="Dimension name (e.g. Technical Depth)"
            value={label}
            onChange={(e) => {
              const v = e.target.value;
              setLabel(v);
              if (!keyTouched) onChange({ key: slugify(v) });
            }}
            className="w-full bg-transparent border-0 border-b-2 border-outline-variant focus:ring-0 focus:border-primary font-headline font-bold text-lg p-0 pb-1"
          />
          <input
            type="text"
            placeholder="dimension_key"
            value={dim.key}
            onChange={(e) => {
              setKeyTouched(true);
              onChange({ key: e.target.value.toLowerCase() });
            }}
            className="w-full bg-transparent border-0 border-b border-outline-variant/50 focus:ring-0 focus:border-primary font-mono text-[11px] text-on-surface-variant p-0"
          />
          <textarea
            value={dim.description}
            onChange={(e) => onChange({ description: e.target.value })}
            placeholder="What does Opus measure for this dimension? Write it the way you'd explain it to a new hiring manager."
            rows={3}
            className="w-full bg-surface border border-outline-variant/30 rounded-lg p-3 text-sm leading-relaxed focus:border-primary focus:ring-0"
          />
        </div>
        <div className="flex flex-col items-end gap-2 min-w-[100px]">
          <div className="flex items-baseline gap-0.5">
            <input
              type="number"
              min={0}
              max={100}
              value={dim.weight}
              onChange={(e) => onChange({ weight: Number(e.target.value) })}
              onBlur={(e) => onChange({ weight: Math.max(0, Math.min(100, Math.round(Number(e.target.value) || 0))) })}
              className="font-headline text-3xl font-black text-primary bg-transparent w-16 text-right appearance-none [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none [-moz-appearance:textfield] focus:outline-none focus:underline focus:decoration-primary/30"
            />
            <span className="text-xs opacity-50">%</span>
          </div>
          <input
            type="range"
            min={0}
            max={100}
            value={dim.weight}
            onChange={(e) => onChange({ weight: Number(e.target.value) })}
            className="w-24"
          />
          {canRemove && (
            <button
              onClick={onRemove}
              className="text-xs text-on-surface-variant hover:text-error transition-colors"
              title="Remove dimension"
            >
              Remove
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function ThresholdRow({
  label,
  hint,
  value,
  onChange,
  accent = false,
  error = false,
}: {
  label: string;
  hint: string;
  value: number;
  onChange: (v: number) => void;
  accent?: boolean;
  error?: boolean;
}) {
  return (
    <div className="flex items-center justify-between p-4 bg-surface-container-low rounded-lg">
      <div>
        <h3 className={`font-headline font-bold text-sm ${error ? "text-error" : ""}`}>
          {label}
        </h3>
        <p className="text-[10px] opacity-70">{hint}</p>
      </div>
      <input
        type="number"
        min={0}
        max={100}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className={`w-16 bg-surface-container-lowest border-0 border-b-2 border-outline-variant focus:ring-0 focus:border-primary text-center font-headline font-black ${
          accent ? "text-primary" : error ? "text-error" : "text-on-surface"
        }`}
      />
    </div>
  );
}

function LabeledInput({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div>
      <label className="block text-[10px] font-label font-bold text-on-surface-variant uppercase tracking-widest mb-2">
        {label}
      </label>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full bg-surface-container-lowest border-0 border-b-2 border-outline-variant focus:ring-0 focus:border-primary py-2 text-sm font-medium"
      />
    </div>
  );
}
