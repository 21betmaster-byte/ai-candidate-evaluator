# Frontend guide — `web/`

Detailed instructions for the Next.js 15 dashboard. If you only want to
boot the dev server, see [README.md](./README.md). If you want to know
how everything fits together, you're in the right place.

## Table of contents

1. [What this app does](#what-this-app-does)
2. [Tech choices](#tech-choices)
3. [Local setup](#local-setup)
4. [Environment variables](#environment-variables)
5. [Sign-in & test users](#sign-in--test-users)
6. [Architecture](#architecture)
   - [The Auth.js HS256 contract](#the-authjs-hs256-contract)
   - [The server-side backend proxy](#the-server-side-backend-proxy)
   - [Server vs client components](#server-vs-client-components)
7. [File map](#file-map)
8. [Rubric editor — how it maps to Opus](#rubric-editor--how-it-maps-to-opus)
9. [How to add a new page / endpoint / component](#how-to-extend-the-app)
10. [Tests](#tests)
    - [Unit (Vitest)](#unit-tests-vitest)
    - [End-to-end (Playwright)](#end-to-end-tests-playwright)
    - [Cross-browser](#cross-browser)
    - [Visual regression](#visual-regression)
11. [Deploying](#deploying)
12. [Troubleshooting](#troubleshooting)

---

## What this app does

A hiring manager opens the dashboard, sees the pipeline of candidates
that the FastAPI backend has processed, drills into one for the full
dossier (rubric scores + reasoning + processing timeline), and either
approves or rejects them. They also use this dashboard to **author the
rubric** that Opus uses to score candidates — that's the demo's
centerpiece.

Three pages:

| Page | Purpose |
|---|---|
| `/candidates` | Pipeline list with filter tabs and sort. Metric cards (total / manual review / avg score). |
| `/candidates/[id]` | Full dossier — verdict, rubric breakdown with per-dimension reasoning, processing timeline, manual pass/fail buttons. |
| `/settings` | Hiring-manager rubric editor: add/remove dimensions, edit descriptions and weights, plus thresholds, polling cadence, company name, pass-email text. |

Plus a sidebar **Poll Now** button that triggers `POST /api/poll` on
the backend.

## Tech choices

- **Next.js 15 App Router** — server components let us fetch the backend
  + render in one round-trip. No client-side data fetching boilerplate.
- **Auth.js v5** — Credentials provider against an in-memory test-user
  list. HS256 JWT shared with the backend (see below).
- **Tailwind 3** + design tokens copied from `stitch/` mockups for visual
  parity. Uses `@tailwindcss/forms`. No CSS-in-JS.
- **Custom Node mock backend** for Playwright e2e tests (necessary
  because `page.route()` can't intercept React Server Component fetches).

No state management library. No data fetching library. Server components
do the fetching server-side; the only client-side data flow is form
state in `SettingsForm` (`useState`) and `useTransition` for action
pending states.

## Local setup

You need:
- Node 20+ (for `npm run dev`)
- The FastAPI backend running on port 8000 (`cd backend && uvicorn app.main:app`)
- Postgres reachable by the backend
- The `0002_rubric_list` migration applied (`alembic upgrade head`)

Then:

```bash
cd web
cp .env.example .env.local
# Edit .env.local — at minimum set AUTH_SECRET to anything ≥32 chars
npm install
npm run dev
```

Open http://localhost:3100. The sign-in form is pre-filled with the
default test user — just click **Sign in**.

## Environment variables

| Variable | Required? | Default | Notes |
|---|---|---|---|
| `AUTH_SECRET` | ✅ yes | — | HS256 signing key. **Must match** `NEXTAUTH_JWT_SECRET` on the backend if the backend allowlist is non-empty. Generate with `openssl rand -base64 48`. |
| `BACKEND_URL` | no | `http://localhost:8000` | Where the server-side proxy forwards `/api/backend/*` requests. Set to your Railway URL in prod. |
| `AUTH_URL` | no | `http://localhost:3100` | Set in prod so Auth.js can build absolute callback URLs. |

`.env.local` is git-ignored. `.env.example` is the canonical template.

## Sign-in & test users

This is an internal platform. Users live in a hardcoded `TEST_USERS`
dict in `web/auth.ts`:

```ts
const TEST_USERS: Record<string, { password: string; name: string }> = {
  "admin@curator.local":  { password: "curator", name: "Admin" },
  "shivam@curator.local": { password: "curator", name: "Shivam" },
};
```

To add a user, add a row. To remove one, delete it. No DB, no IdP.

If you want to swap to a real provider (Google Workspace, Okta, etc.),
the change is small: add the provider in `auth.ts`, keep the existing
HS256 `jwt.encode`/`jwt.decode` overrides so the backend contract holds.

The backend has a parallel allowlist in `backend/.env::ALLOWED_EMAILS`.
Any user you add here must also be added there. (If `ALLOWED_EMAILS` is
empty, the backend runs in dev mode and trusts the `X-User-Email`
header — fine for local work.)

## Architecture

### The Auth.js HS256 contract

The backend (`backend/app/auth.py`) expects every request to carry
`Authorization: Bearer <jwt>` where the JWT is signed with HS256 against
a shared secret. Auth.js v5 defaults to a JWE (encrypted, opaque), which
the backend can't verify.

`auth.ts` overrides Auth.js's `jwt.encode` and `jwt.decode` to emit a
plain HS256 JWT instead, using `jose`:

```ts
jwt: {
  encode: async ({ token, maxAge }) =>
    new SignJWT(token).setProtectedHeader({ alg: "HS256" }).sign(secret),
  decode: async ({ token }) =>
    (await jwtVerify(token, secret, { algorithms: ["HS256"] })).payload,
},
```

The HS256 token is then stored in the session cookie verbatim (Auth.js
treats the encode output as the cookie value), so the proxy can lift it
straight out of the cookie and forward it as-is. **Zero re-signing per
request, zero raw token in the browser.**

### The server-side backend proxy

`src/app/api/backend/[...path]/route.ts` is a transparent forwarder:

1. Reads the Auth.js session cookie (the HS256 JWT).
2. Verifies the session is valid via `auth()`.
3. Strips hop-by-hop headers from the inbound request.
4. Adds `Authorization: Bearer <jwt>` and `X-User-Email: <email>`.
5. Forwards to `${BACKEND_URL}/api/${subpath}` with the original method
   and body.
6. Strips hop-by-hop headers from the response.
7. Streams the response body back to the client.

The browser only ever talks to the same-origin Next.js app. CORS does
not apply. The JWT never reaches the browser.

This is why **all** backend calls — including the ones that React Server
Components make from inside Node — go through `/api/backend/...`. In a
server component:

```ts
import { backend } from "@/lib/backend";
const settings = await backend.getSettings({ baseUrl, cookieHeader });
```

In a client component:

```ts
"use client";
import { backend } from "@/lib/backend";
const settings = await backend.getSettings();   // same-origin, cookie automatic
```

The `backend` helper detects which environment it's running in and
builds the URL appropriately.

### Server vs client components

| Concern | Component type |
|---|---|
| Initial page render with backend data | Server component (`async function Page()`) |
| Form state, validation, slider drag | Client component (`"use client"`) |
| Buttons that POST and refresh | Client component using `useTransition` + `router.refresh()` |
| Sidebar, top nav, layout shell | Server component (no interactivity) |
| Poll-Now button (interactive) | Client component nested inside the server SideNav |

Rule of thumb: start as a server component, only add `"use client"` if
you need state, effects, or browser APIs.

## File map

```
auth.ts                          Auth.js v5 config + HS256 override + TEST_USERS
playwright.config.ts             Playwright config — 3 browsers × 3 auth states
vitest.config.ts                 Vitest config — jsdom + @ alias
tailwind.config.ts               Design tokens copied from stitch/ mockups
next.config.ts
postcss.config.mjs
tsconfig.json
package.json

src/
├── middleware.ts                Gate every page except /signin behind a session
├── app/
│   ├── layout.tsx               Root layout — fonts, globals
│   ├── globals.css              Tailwind + range-slider + material symbols styles
│   ├── page.tsx                 Redirect → /candidates
│   ├── signin/page.tsx          Sign-in form (Credentials provider)
│   ├── api/
│   │   ├── auth/[...nextauth]/route.ts   Auth.js catch-all
│   │   └── backend/[...path]/route.ts    Server-side proxy → FastAPI
│   └── (dashboard)/
│       ├── layout.tsx           SideNav + TopNav shell
│       ├── candidates/
│       │   ├── page.tsx         List page (server component)
│       │   └── [id]/page.tsx    Detail page (server component)
│       └── settings/page.tsx    Rubric editor entry (server component)
├── components/
│   ├── SideNav.tsx              Sidebar with Poll-Now + sign-out
│   ├── TopNav.tsx               Top bar
│   ├── PollNowButton.tsx        POST /api/backend/poll (client)
│   ├── CandidateRow.tsx         List row
│   ├── DecisionButtons.tsx      Manual pass/fail (client)
│   └── SettingsForm.tsx         Rubric editor (client) — the demo's centerpiece
└── lib/
    ├── types.ts                 DTOs mirroring backend/app/schemas.py
    └── backend.ts               Typed fetch helpers — works server and client side

tests/
├── unit/                        Vitest — 47 tests
│   ├── setup.tsx                Stubs next/navigation + next/link for jsdom
│   ├── settings-form.test.tsx   19 tests — the rubric editor's full validation
│   ├── candidate-row.test.tsx   17 tests — every status, edge cases
│   ├── poll-now-button.test.tsx 5 tests — every state
│   └── decision-buttons.test.tsx 6 tests — enable/disable, payloads, errors
└── e2e/                         Playwright — 99 tests across 3 browsers
    ├── auth.setup.ts            One-shot sign-in → .auth/{browser}.json
    ├── fixtures.ts              Mock-server control + DTO factories
    ├── mock-server/
    │   └── server.mjs           Tiny Node HTTP mock backend (port 8765)
    ├── sign-in.spec.ts
    ├── auth-gate.spec.ts
    ├── candidates.spec.ts
    ├── candidate-detail.spec.ts
    ├── settings.spec.ts         The demo-critical settings e2e
    ├── poll-now.spec.ts
    ├── visual.spec.ts           Visual regression — 4 pages × 3 browsers
    └── __screenshots__/         Committed visual baselines
```

## Rubric editor — how it maps to Opus

This is the heart of the product. The hiring manager opens `/settings`
and edits a list of dimensions. Each dimension has:

| Field | Constraint | What Opus sees |
|---|---|---|
| `key` | `^[a-z0-9][a-z0-9_]{0,63}$` | Echoed back in the scores dict |
| `description` | 1–500 chars, non-blank | Passed verbatim as the *authoritative definition* of the dimension |
| `weight` | 0–100 integer | Used by `compute_weighted` for the overall score |

The editor enforces these client-side mirroring the backend's pydantic
rules exactly:

- At least one dimension
- Unique keys
- Weights sum to exactly 100
- Auto-fail < manual-review < auto-pass thresholds

When the hiring manager clicks **Save**, the form POSTs to
`PUT /api/backend/settings`, the backend re-validates with the same
rules in `backend/app/schemas.py::SettingsModel`, and persists. The next
candidate run picks up the new rubric automatically:
`backend/app/jobs/handlers.py::handle_score` reads `settings.rubric` and
passes the full list (descriptions and all) to
`backend/app/pipeline/score.py::score_candidate`, which renders it as:

```
RUBRIC (each dimension is authored by the hiring manager — use the
description as the authoritative definition of what to measure):
- design_taste (weight: 40%)
    Description: Eye for visual craft — proportion, restraint, tasteful motion.
- storytelling (weight: 35%)
    Description: Explains their work like a PM pitching a narrative.
- builder_mindset (weight: 25%)
    Description: Strong bias to shipping over perfect planning.
```

…and asks Opus to score against it. **Opus does not see the
implementation — it sees only the descriptions you write.** This is
why the editor's validation is strict and the unit/e2e tests are
exhaustive: a typo in a description goes straight into production
scoring.

⚠️ **Editing the rubric does NOT re-score existing candidates.** Old
scores are preserved; only new candidates get the new rubric. This is
a deliberate trade-off (PRD §7) to keep things predictable.

## How to extend the app

### Add a new dashboard page

1. Create `src/app/(dashboard)/<route>/page.tsx` as a server component.
2. Fetch backend data with the typed client:

```ts
import { headers } from "next/headers";
import { backend } from "@/lib/backend";

export default async function MyPage() {
  const h = await headers();
  const baseUrl = `${h.get("x-forwarded-proto") ?? "http"}://${h.get("host")}`;
  const cookieHeader = h.get("cookie") ?? undefined;
  const data = await backend.somethingNew({ baseUrl, cookieHeader });
  return <pre>{JSON.stringify(data, null, 2)}</pre>;
}
```

3. Add a sidebar link in `src/components/SideNav.tsx`.

### Add a new backend endpoint to the typed client

1. Add the DTO to `src/lib/types.ts` (mirror `backend/app/schemas.py`).
2. Add a method to `src/lib/backend.ts`:

```ts
somethingNew(opts?: FetchOpts) {
  return request<NewDTO>("/something/new", {}, opts);
},
```

3. Both server and client components can now `await backend.somethingNew()`.

### Add a client-side interaction

`"use client";` at the top of the file. Use `useState` for form state,
`useTransition` for pending UI, and `router.refresh()` to re-fetch the
parent server component after a mutation.

See `src/components/DecisionButtons.tsx` for a minimal example and
`src/components/SettingsForm.tsx` for a maximal one.

## Tests

Three runners, all hermetic.

### Unit tests (Vitest)

```bash
npm test                          # one-shot, ~1.4s
npm run test:watch                # interactive
npx vitest run settings-form      # one file
```

47 tests covering:

- **`SettingsForm`** (19) — every validation rule, auto-slugify
  behavior, add/remove, distribute-evenly arithmetic, save payload
  shape, backend error surfacing.
- **`CandidateRow`** (17) — every status badge, score edge cases (null,
  0, 100), unicode names, long emails, initials.
- **`PollNowButton`** (5) — idle / pending / success (singular vs
  plural) / "up to date" / error.
- **`DecisionButtons`** (6) — enable/disable, POST payloads, refresh
  on success, error inline.

Vitest stubs `next/navigation` and `next/link` in `tests/unit/setup.tsx`
so client components can render in jsdom without the Next runtime.

### End-to-end tests (Playwright)

```bash
npx playwright test                          # everything (99 tests, ~96s)
npx playwright test settings.spec.ts         # one file
npx playwright test --ui                     # interactive UI
npx playwright show-report                   # HTML report after a run
```

**Architecture (important).** React Server Components fetch the
backend from inside Node, so Playwright's `page.route()` cannot
intercept those calls. We work around it with a tiny Node HTTP mock
backend at `tests/e2e/mock-server/server.mjs`:

- Playwright launches the mock on port 8765 alongside the dev server
- The dev server runs with `BACKEND_URL=http://localhost:8765`
- Tests push canned responses into the mock via `POST /__mock/set`
  before each test, then assert on what the dashboard rendered
- Tests read recorded calls back via `GET /__mock/calls` to verify
  payloads (e.g. the exact rubric the Save button POSTed)

Helpers live in `tests/e2e/fixtures.ts`: `resetMocks()`, `setMocks()`,
`getMockCalls()`, plus DTO factories (`makeSettings`,
`makeCandidateDetail`, `makeCandidateRow`).

Specs:

| File | Coverage |
|---|---|
| `auth.setup.ts` | One-shot sign-in, persists auth state per browser |
| `sign-in.spec.ts` | Happy path + wrong password + unknown email + `from=` redirect |
| `auth-gate.spec.ts` | Unauth `/candidates`, `/settings`, `/candidates/42` redirect to `/signin` |
| `candidates.spec.ts` | Empty state, 3-row render, filter tabs, sort, row click, 500 error |
| `candidate-detail.spec.ts` | Identity + verdict + rubric sidebar, **custom dimension names**, awaiting state, Approve POST + refresh, disabled buttons, 404 |
| `settings.spec.ts` | The demo-critical suite — load, edit, add custom dimension, remove, validation errors, backend 400, threshold + company round-trip |
| `poll-now.spec.ts` | Cadence hint, "X new messages", "up to date", error without hanging |
| `visual.spec.ts` | Full-page screenshots of 4 demo screens × 3 browsers |

### Cross-browser

The Playwright config defines projects for Chromium, Firefox, and WebKit
× three auth states (setup, authenticated, unauthenticated):

```bash
npx playwright test                                       # all 3 browsers
npx playwright test --project=authenticated-chromium      # Chromium only
npx playwright test --project=authenticated-firefox       # Firefox only
npx playwright test --project=authenticated-webkit        # WebKit (Safari) only
```

Each browser gets its own auth state file at `.auth/{browser}.json`.
`workers: 1` keeps the suite hermetic — the Node mock backend is a
single shared process, so parallel tests would stomp on each other's
canned responses.

### Visual regression

`tests/e2e/visual.spec.ts` captures four full-page screenshots and
asserts byte-similarity against committed baselines:

1. Sign-in page
2. Candidates list (with 3 seeded rows)
3. Candidate detail (Alice with full evaluation)
4. Settings rubric editor

12 baselines total (4 pages × 3 browsers), stored at
`tests/e2e/__screenshots__/visual.spec.ts/{name}-{project}.png`. The
functional tests check semantic structure (roles, text); these catch
the layout bugs the functional tests miss — typo'd Tailwind classes,
wrong color tokens, regressed font weights.

**Determinism baked in:**
- Viewport pinned to 1280×800
- Mock backend returns identical seed data every run
- Frozen timestamps in seed data
- Animations disabled
- Tolerance: `maxDiffPixelRatio: 0.02`, `threshold: 0.2` for
  sub-pixel anti-aliasing

**Updating baselines after intentional UI work:**

```bash
npx playwright test visual.spec.ts --update-snapshots
# Then review the diff in tests/e2e/__screenshots__/ before committing
```

If the diff doesn't match what you intended, fix the code, not the
baseline.

## Deploying

The Railway config at the repo root only builds the backend
(`railway.json` references `backend/Dockerfile`). The frontend is meant
to be deployed separately to Vercel or another Node host:

1. `BACKEND_URL` → your Railway backend URL
2. `AUTH_SECRET` → identical to the backend's `NEXTAUTH_JWT_SECRET`
3. `AUTH_URL` → your dashboard's public URL
4. Add the production user emails to the backend's `ALLOWED_EMAILS`
   AND to `web/auth.ts::TEST_USERS`

Vercel auto-detects Next.js. `npm run build` is the build command,
`npm run start` is the start command (or just let Vercel handle it).

Don't ship the dev `AUTH_SECRET` value from `.env.example` to prod —
generate a fresh one with `openssl rand -base64 48`.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `MissingSecret` from Auth.js on every request | `AUTH_SECRET` not set | Create `.env.local` with a real secret. Restart `npm run dev`. |
| Sign-in succeeds but every backend call returns 401 | `AUTH_SECRET` doesn't match the backend's `NEXTAUTH_JWT_SECRET` | Make them identical in both env files. |
| Sign-in succeeds in dev but breaks after deploy | Forgot to set `AUTH_URL` in prod | Set it to the dashboard's public URL. |
| Auth gate not redirecting unauth requests | `middleware.ts` not picked up | Confirm it's at `src/middleware.ts` (not the project root). Restart the dev server — Next.js doesn't hot-reload middleware reliably. |
| Dev server logs `ECONNREFUSED ::1:8000` | Backend not running | Start it (`cd ../backend && uvicorn app.main:app`). |
| Settings page shows "Couldn't load settings" | Backend reachable but `/api/settings` returned non-200 | Check the backend log; common cause is the migration not having been run (`alembic upgrade head`). |
| Vitest can't find a label / role | Component missing `htmlFor`/`id` or `aria-label` | Real accessibility bug. Fix the component, not the test. |
| Playwright `auth.setup.ts` times out at email field | Old dev server cached, missing label fix | Stop the dev server, re-run `npx playwright test` (it'll spawn a fresh one). |
| Playwright errors with `ECONNREFUSED 8765` | Mock server didn't start | Run `node tests/e2e/mock-server/server.mjs` standalone to debug. |
| Visual regression fails after a real UI change | Baselines are stale | `npx playwright test visual.spec.ts --update-snapshots`, review the diff, commit. |
| Visual regression fails on one browser only | Browser-specific rendering quirk | Inspect the diff PNG. Either tighten the tolerance or accept the new baseline. |
| Cross-browser tests run sequentially and feel slow | Intentional — `workers: 1` because the mock backend is a shared process | Run a single browser project for fast iteration. |

## See also

- **[../README.md](../README.md)** — top-level project overview
- **[../TESTING.md](../TESTING.md)** — full test runbook for all four tiers
- **[../backend/BACKEND_STATUS.md](../backend/BACKEND_STATUS.md)** — backend deep dive
- **[../PRD_AI_Candidate_Evaluator_V1.md](../PRD_AI_Candidate_Evaluator_V1.md)** — product requirements
