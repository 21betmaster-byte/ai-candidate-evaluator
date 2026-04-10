/**
 * Test helpers: backend response factories + mock-server control.
 *
 * The dashboard pages are React Server Components that fetch from
 * BACKEND_URL inside Node, so we cannot intercept those calls with
 * Playwright's `page.route()`. Instead we point BACKEND_URL at a tiny
 * Node mock backend (tests/e2e/mock-server/server.mjs) and push canned
 * responses into it via HTTP control endpoints from these helpers.
 *
 * Each test typically:
 *   1. Calls `await resetMocks()`             // wipe state
 *   2. Calls `await setMocks({...})`          // inject canned responses
 *   3. Navigates the page                     // which fetches the mocks
 *   4. Asserts on the rendered DOM
 *   5. Optionally calls `await getMockCalls()` to verify the payload
 */
import type {
  CandidateDetail,
  CandidateRow,
  ProcessingLogEntry,
  SettingsModel,
} from "../../src/lib/types";

const MOCK_BASE = process.env.MOCK_BACKEND_URL ?? "http://localhost:8765";

// ---------------------------- Factories ----------------------------------

export function makeCandidateRow(
  overrides: Partial<CandidateRow> = {},
): CandidateRow {
  return {
    id: 1,
    email: "alice@example.com",
    name: "Alice Jones",
    status: "manual_review",
    overall_score: 82.5,
    created_at: "2026-04-05T09:00:00Z",
    ...overrides,
  };
}

export function makeSettings(overrides: Partial<SettingsModel> = {}): SettingsModel {
  return {
    polling_minutes: 2,
    rubric: [
      {
        key: "technical_depth",
        description: "Engineering chops: systems, stack fluency, trade-offs.",
        weight: 40,
      },
      {
        key: "shipped_products",
        description: "Track record of launching real products end-to-end.",
        weight: 35,
      },
      {
        key: "business_thinking",
        description: "Connects engineering decisions to user + business outcomes.",
        weight: 25,
      },
    ],
    tier_thresholds: {
      auto_fail_ceiling: 49,
      manual_review_ceiling: 69,
      auto_pass_floor: 70,
    },
    pass_next_steps_text: "Reply with times that work for a 30-min call.",
    reminder_hours: 48,
    incomplete_expiry_days: 7,
    company_name: "Curator",
    ...overrides,
  };
}

export function makeCandidateDetail(
  overrides: Partial<CandidateDetail> = {},
): CandidateDetail {
  const id = overrides.id ?? 1;
  return {
    id,
    email: "alice@example.com",
    name: "Alice Jones",
    status: "manual_review",
    missing_items: null,
    review_source: null,
    review_reason: null,
    created_at: "2026-04-05T09:00:00Z",
    updated_at: "2026-04-05T09:30:00Z",
    email_history: [],
    current_evaluation: {
      id: 100,
      superseded: false,
      github_url: "https://github.com/alice",
      portfolio_url: "https://alice.dev",
      resume_filename: "alice_resume.pdf",
      structured_profile: {
        name: "Alice Jones",
        headline: "Design-minded full-stack engineer",
        years_of_experience: 8,
        current_role: "Staff Engineer @ FinTech Global",
        work_experience: [
          {
            company: "FinTech Global",
            title: "Staff Engineer",
            duration: "2020 — Present",
            highlights: [
              "Led migration from monolith to service mesh",
              "Shipped internal developer platform adopted by 120 engineers",
            ],
          },
        ],
        shipped_products: [
          { name: "Helix DX", description: "Internal developer experience platform." },
        ],
        github_signal: {
          active: true,
          primary_languages: ["TypeScript", "Go"],
          activity_summary: "Daily commits, 12 public repos.",
          total_public_repos: 12,
        },
      },
      scores: {
        technical_depth: { score: 91, reasoning: "Strong systems work and deep stack fluency." },
        shipped_products: { score: 85, reasoning: "Led internal DX platform adopted by 120 engineers." },
        business_thinking: { score: 74, reasoning: "Connects infra choices to engineer productivity metrics." },
      },
      overall_score: 84.1,
      tier: "manual_review",
      decision_reason:
        "Strong builder with clear production impact and tasteful design thinking.",
      created_at: "2026-04-05T09:20:00Z",
    },
    logs: [
      makeLog({ step: "parse_resume", message: "parsed alice_resume.pdf (12 pages)" }),
      makeLog({ step: "fetch_github", message: "fetched github/alice — 12 repos" }),
      makeLog({ step: "score", message: "overall=84.1 tier=manual_review" }),
    ],
    ...overrides,
  };
}

export function makeLog(overrides: Partial<ProcessingLogEntry> = {}): ProcessingLogEntry {
  return {
    id: Math.floor(Math.random() * 1e9),
    step: "score",
    level: "info",
    message: "ok",
    meta: null,
    created_at: "2026-04-05T09:20:00Z",
    ...overrides,
  };
}

// ---------------------------- Mock control --------------------------------

type MockResponse = { status?: number; body?: unknown };

/** Wipe all canned responses + recorded calls. Call once per test. */
export async function resetMocks(): Promise<void> {
  const r = await fetch(`${MOCK_BASE}/__mock/reset`, { method: "POST" });
  if (!r.ok) throw new Error(`mock-server reset failed: ${r.status}`);
}

/** Inject canned responses keyed by `"METHOD /path"` (with `:id` for params). */
export async function setMocks(
  responses: Record<string, MockResponse>,
): Promise<void> {
  const r = await fetch(`${MOCK_BASE}/__mock/set`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(responses),
  });
  if (!r.ok) {
    const text = await r.text();
    throw new Error(`mock-server set failed: ${r.status} ${text}`);
  }
}

/** Read every call the mock server has received since the last reset. */
export async function getMockCalls(): Promise<
  { method: string; path: string; query: Record<string, string>; body: unknown }[]
> {
  const r = await fetch(`${MOCK_BASE}/__mock/calls`);
  if (!r.ok) throw new Error(`mock-server calls failed: ${r.status}`);
  return (await r.json()) as ReturnType<typeof getMockCalls> extends Promise<infer T>
    ? T
    : never;
}

// ---------------------------- High-level helpers --------------------------

/**
 * Convenience: seed the dashboard's "default" responses so navigation works.
 * Tests can layer their own setMocks() on top.
 */
export async function seedDefaults(extra: Record<string, MockResponse> = {}) {
  await resetMocks();
  await setMocks({
    "GET /api/settings": { status: 200, body: makeSettings() },
    "GET /api/candidates": { status: 200, body: [] },
    ...extra,
  });
}
