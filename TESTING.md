# Testing — 

The product has four test tiers. Three are hermetic and fast (no network,
no real services). One is opt-in and hits real Gmail. Run the hermetic
ones before every commit. Run the live tier before every deploy and
before every demo.

## Snapshot

| Tier                          | Runner    | Tests   | Wall time | What it locks down |
|------------------------------|-----------|---------|-----------|--------------------|
| Backend (hermetic)           | pytest    | 56      | ~0.1s     | Rubric schema validation, /api/settings round-trip, Opus prompt assembly, weighted-score math |
| Backend (live, opt-in)       | pytest -m live | 4  | ~30s      | Real Gmail OAuth, send/list/fetch/mark-processed, poll_inbox happy path, error surfacing |
| Frontend unit                | Vitest    | 47      | ~1.4s     | SettingsForm validation, CandidateRow rendering, Poll/Decision button states |
| End-to-end (cross-browser)   | Playwright| 99      | ~96s      | Sign-in, dashboard navigation, settings round-trip, manual decisions, **visual regression**, all on Chromium + Firefox + WebKit |
| **Default total**            |           | **202** | **~98s**  | (live tier excluded by default) |

Run the hermetic tiers all in one shot from the repo root:

```bash
# 1. Backend
cd backend && source .venv/bin/activate && pytest

# 2. Frontend unit
cd ../web && npm test

# 3. Frontend e2e + visual + cross-browser
npx playwright test
```

Run the live Gmail tier separately when you need to validate the inbox
plumbing — it's slow and touches real Gmail:

```bash
cd backend && source .venv/bin/activate && \
  GMAIL_LABEL_PROCESSED=evaluator/test-live RUN_LIVE_TESTS=1 \
  pytest -m live
```

---

## Tier 1 — Backend (pytest)

**Where:** `backend/tests/`
**Runner:** pytest with the existing in-memory SQLite + monkeypatched LLM fixtures.
**Setup:** none. Reuses `backend/.venv` and the existing `conftest.py`.

```bash
cd backend
source .venv/bin/activate
pytest                                           # everything
pytest tests/test_rubric_schema.py -v            # only the rubric pydantic suite
pytest tests/test_settings_api.py::TestSettingsPutValidation -v
pytest tests/test_score_prompt.py -k custom      # only custom-dimension tests
```

### Files

- **`tests/test_rubric_schema.py`** — Pydantic-level validation of
  `RubricDimension` and `SettingsModel`. Locks down: weights summing to 100,
  unique keys, valid slug regex, non-blank descriptions, weight bounds,
  description length cap, and that custom dimension names (e.g.
  `design_taste`) are accepted.
- **`tests/test_settings_api.py`** — `/api/settings` GET/PUT integration
  tests against FastAPI's `TestClient`. Verifies the full HTTP round-trip
  including: persistence across requests, custom dimensions surviving the
  round-trip, threshold updates not stomping the rubric, and every
  validation failure returning 4xx (never 500).
- **`tests/test_score_prompt.py`** — Locks down the *Opus contract*: the
  hiring manager's descriptions must reach Opus verbatim, and Opus
  responses with custom keys must be mapped back correctly. Patches
  `call_opus` and inspects the user message for every dimension's key,
  weight, and description.
- **`tests/test_score_compute.py`** — `compute_weighted` math against a
  custom rubric.

### What it does NOT cover

- Real Anthropic API calls (mocked).
- Real Gmail polling (covered separately by **Tier 1b — live Gmail**).
- Real Postgres (uses SQLite via the JSONB→JSON shim).

The full backend pipeline is covered by the pre-existing
`tests/test_e2e.py` suite, which still passes against the new rubric shape.

---

## Tier 1b — Live Gmail integration (opt-in)

**Where:** `backend/tests/test_gmail_live.py`
**Runner:** pytest with `-m live`
**Setup:** the same backend `.venv` plus a real Gmail OAuth refresh
token in `backend/.env` (the same one prod uses).

```bash
cd backend
source .venv/bin/activate

# IMPORTANT: override the processed-label so live tests cannot touch
# production candidate state. The test module also refuses to run if
# this is not set.
export GMAIL_LABEL_PROCESSED=evaluator/test-live
export RUN_LIVE_TESTS=1

pytest -m live -v
# or just one suite:
pytest -m live tests/test_gmail_live.py::TestGmailLivePolling -v
```

Both `RUN_LIVE_TESTS=1` and `pytest -m live` can be used to opt in;
you only need one of them.

### What it covers

- **`TestGmailLiveOAuth`** — Smoke check that the OAuth refresh token
  still mints access tokens. If this fails, the token is dead and you
  need to re-issue it via `backend/scripts/get_gmail_refresh_token.py`.
- **`TestGmailLivePolling`** — Sends a unique-subject test message FROM
  the inbox TO itself, polls for it, fetches its parsed `InboundEmail`,
  marks it processed, then re-polls and verifies it's gone from the
  unprocessed list.
- **`TestGmailLivePollerIntegration`** — Calls the higher-level
  `poll_inbox()` function — the same code path the production worker
  runs every N minutes — and verifies it returns a non-zero count when
  there are real messages waiting.
- **`TestGmailLiveErrorPaths`** — Verifies the client surfaces real
  Google API errors as Python exceptions instead of swallowing them.

### Safety properties

1. **Unique subjects.** Every test message uses a UUID-tagged subject
   like `[TEST-LIVE-a1b2c3d4e5f6] integration check`, so we never
   confuse it with a real candidate email.
2. **Self-send only.** Test messages are sent FROM the configured inbox
   TO itself. We never email an outside address.
3. **Separate processed label.** The module refuses to run unless
   `GMAIL_LABEL_PROCESSED=evaluator/test-live` (or any non-prod label)
   is set, so production candidate state is never touched.
4. **Aggressive cleanup.** Each test uses a `cleanup_message_id`
   fixture with try/finally semantics. After the test, every message id
   it touched is moved to Trash via the Gmail API. Cleanup is best-
   effort: if Gmail is unreachable on teardown, the test message is
   left in trash for manual cleanup but the test still reports pass/fail
   correctly.
5. **No production pipeline.** These tests exercise the Gmail client
   primitives only. They never run a candidate through `classify →
   structure → score → send_decision_email`, so no candidate-facing
   email is ever generated.
6. **Default-skipped.** `pyproject.toml` has `addopts = "-m 'not live'"`,
   so the regular `pytest` invocation deselects them. CI is opt-in.

### What it does NOT cover

- The full pipeline against a real candidate email (would send real
  ack/decision emails and call real Anthropic). For that, set up a
  dedicated test inbox with a tagged subject filter and run the e2e
  pipeline against it manually before deploys.

---

## Tier 2 — Frontend unit (Vitest)

**Where:** `web/tests/unit/`
**Runner:** Vitest + jsdom + React Testing Library.
**Setup:** `npm install` once.

```bash
cd web
npm test                          # one-shot
npm run test:watch                # interactive
npx vitest run settings-form      # one file
```

### Files

- **`tests/unit/settings-form.test.tsx`** — 19 tests covering the
  demo-critical rubric editor. Validates the client mirrors the backend's
  pydantic invariants exactly: weights sum, unique keys, blank
  descriptions, ordered thresholds, slug-key regex. Plus auto-slugify
  behavior (name → key, stops on manual edit), add/remove dimensions,
  distribute-evenly, save payload shape, and backend error surfacing.
- **`tests/unit/candidate-row.test.tsx`** — 17 tests covering every status
  badge, score rendering edge cases (null, 0, 100), unicode names, long
  emails, initials computation.
- **`tests/unit/poll-now-button.test.tsx`** — 5 tests for idle / pending
  / success / "up to date" / error states.
- **`tests/unit/decision-buttons.test.tsx`** — 6 tests for enable/disable
  rules, POST payloads, and error surfacing.

### What it does NOT cover

- Server components (layouts, page entry points). Vitest can't import
  `next/headers` etc. — that's what Playwright covers.

---

## Tier 3 — End-to-end (Playwright)

**Where:** `web/tests/e2e/`
**Runner:** Playwright + headless Chromium.
**Setup:** `npm install` once + `npx playwright install chromium` once.

```bash
cd web
npx playwright test                          # everything
npx playwright test settings.spec.ts         # one file
npx playwright test --ui                     # interactive UI
npx playwright show-report                   # post-mortem HTML report
```

### Architecture

Playwright launches **two** webServers in parallel:

1. **Mock FastAPI backend** — `tests/e2e/mock-server/server.mjs`, a tiny
   Node HTTP server on port 8765. Tests push canned responses into it via
   `POST /__mock/set` and read back the recorded calls via `GET /__mock/calls`.
2. **Next.js dev server** — `npm run dev` on port 3100, with `BACKEND_URL`
   pointed at the mock so server-side fetches from React Server
   Components hit the mock instead of a real backend.

This is why we can't use Playwright's `page.route()` for these tests:
React Server Components fetch from inside Node, not the browser.
`page.route()` only sees browser traffic.

The mock server has three control endpoints:

| Endpoint | Purpose |
|---|---|
| `POST /__mock/reset` | Wipe canned responses + recorded calls |
| `POST /__mock/set` | Add canned responses keyed by `"METHOD /path"` (`:id` placeholders supported) |
| `GET /__mock/calls` | Read every request the dashboard has made |

The helpers in `tests/e2e/fixtures.ts` wrap these.

### Files

- **`tests/e2e/auth.setup.ts`** — Signs in once, persists the session
  cookie to `.auth/user.json`. Other tests reuse it via Playwright's
  `storageState` so they don't re-walk the sign-in form.
- **`tests/e2e/fixtures.ts`** — Mock control helpers + DTO factories
  (`makeSettings`, `makeCandidateDetail`, `makeCandidateRow`, `makeLog`).
- **`tests/e2e/sign-in.spec.ts`** — Real Credentials provider flow:
  happy path, wrong password, unknown email, `from=` redirect.
- **`tests/e2e/auth-gate.spec.ts`** — Unauthenticated `/candidates`,
  `/settings`, `/candidates/:id` all redirect to `/signin?from=...`.
- **`tests/e2e/candidates.spec.ts`** — Empty state, full list, filter
  tabs (URL + refetch), row click navigation, backend 500 error state.
- **`tests/e2e/candidate-detail.spec.ts`** — Identity + verdict + rubric
  sidebar render; **custom hiring-manager dimensions** render with the
  right names and reasoning; "Awaiting evaluation" empty state; Approve
  POST + status refresh; disabled buttons for already-decided candidates;
  Next 404 for unknown id.
- **`tests/e2e/settings.spec.ts`** — *The demo-critical suite.* Loads
  the rubric, edits a description and verifies the PUT payload, adds a
  brand-new `design_taste` dimension end-to-end, removes a dimension,
  surfaces a backend 400 error, threshold + company + pass-email
  round-trip in a single save.
- **`tests/e2e/poll-now.spec.ts`** — Sidebar Poll Now button: cadence
  hint, "X new messages", "up to date", error state without hanging.

### Test artifacts

On failure, Playwright writes:
- A screenshot to `test-results/.../test-failed-1.png`
- A video of the run to `test-results/.../video.webm`
- A trace zip you can open with `npx playwright show-trace <file>`
- The full HTML report at `playwright-report/index.html` (run
  `npx playwright show-report` to open it in a browser)

### Cross-browser

The Playwright config defines a project per browser × auth state matrix:

| Browser  | setup-* | authenticated-* | unauthenticated-* |
|----------|---------|------------------|-------------------|
| Chromium | ✓       | ✓                | ✓                 |
| Firefox  | ✓       | ✓                | ✓                 |
| WebKit   | ✓       | ✓                | ✓                 |

Each browser runs the full functional + visual suite, so the same regression
on, say, Safari that wouldn't show up in Chrome gets caught immediately.

Run a single browser when you only need a quick check:

```bash
npx playwright test --project=authenticated-chromium      # functional only on Chrome
npx playwright test --project=authenticated-firefox       # functional only on Firefox
npx playwright test --project=authenticated-webkit        # functional only on Safari
```

### Visual regression — `tests/e2e/visual.spec.ts`


| Screen | File |
|---|---|
| Sign-in page | `sign-in-{authenticated-browser}.png` |
| Candidates list | `candidates-list-{authenticated-browser}.png` |
| Candidate detail | `candidate-detail-{authenticated-browser}.png` |
| Settings rubric editor | `settings-rubric-{authenticated-browser}.png` |

12 baselines total (4 screens × 3 browsers), all committed to
`web/tests/e2e/__screenshots__/visual.spec.ts/`. The functional tests
catch broken behavior; the visual tests catch broken layout — a typo'd
Tailwind class, a wrong color token, a regressed font weight.

**Determinism:**
- Viewport pinned to 1280×800.
- The mock backend returns identical seed data on every run.
- Animations disabled via `animations: "disabled"`.
- Tolerance set to `maxDiffPixelRatio: 0.02` and `threshold: 0.2` to
  absorb sub-pixel anti-aliasing differences across machines.

**When intentional UI work changes a screen:**

```bash
npx playwright test visual.spec.ts --update-snapshots
```

Then *review the diff in `tests/e2e/__screenshots__/`*. If it reflects
the intentional change, commit. If not, you've introduced a layout bug —
fix the code, not the baseline.

### What it does NOT cover

- Real Anthropic API calls (the mock backend never proxies them).
- Real Gmail polling — covered separately by the live backend tier.
- Visual regression on viewports other than 1280×800. Add a `mobile-*`
  project in `playwright.config.ts` if you need responsive guards.

---

## Demo-day checklist

Before opening the dashboard for leadership, run **all four tiers**:

```bash
# 1) Backend (hermetic) — locks down the rubric/score contracts
cd backend && source .venv/bin/activate && pytest -q

# 2) Backend (live Gmail) — proves the real inbox plumbing works
GMAIL_LABEL_PROCESSED=evaluator/test-live RUN_LIVE_TESTS=1 pytest -m live -q

# 3) Frontend unit
cd ../web && npm test

# 4) Frontend e2e + visual + cross-browser (Chromium / Firefox / WebKit)
npx playwright test
```

All four should be green. If any are red, do not proceed.

If the live Gmail tier is the only one red, the dashboard still works
but the inbox poller is broken — investigate before the demo because
new candidate emails won't flow through. Common causes: expired refresh
token, revoked OAuth client, hit Gmail API quota.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `mock-server: no canned response for ...` 404 in browser | A test forgot to seed a response | Add the missing key to `setMocks(...)` in the test's `beforeEach` |
| `auth.setup.ts` times out at the email field | Old dev server cached without `htmlFor` on labels | Stop the dev server and let Playwright spawn a fresh one |
| `MissingSecret` from Auth.js | `.env.local` missing or empty `AUTH_SECRET` | `cp .env.example .env.local` and edit |
| All e2e tests fail with "ECONNREFUSED 8765" | Mock server didn't start | Check `tests/e2e/mock-server/server.mjs` runs standalone; check port 8765 isn't taken |
| Vitest can't find a label | `<label>` missing `htmlFor`, or input missing matching `id` | Real accessibility bug. Fix the component, not the test. |
| Visual regression fails after a real UI change | Baselines are stale | Review the diff in `tests/e2e/__screenshots__/`, then `npx playwright test visual.spec.ts --update-snapshots` and commit |
| Visual regression fails on one browser only | Browser-specific rendering quirk (font hinting, scrollbar width) | Either tighten `maxDiffPixelRatio` for that platform or accept the new baseline |
| Live Gmail tests fail at OAuth step | Refresh token expired or revoked | Re-issue with `backend/scripts/get_gmail_refresh_token.py`, update `backend/.env` |
| Live Gmail tests refuse to run with "Refusing to run live tests against the production label" | `GMAIL_LABEL_PROCESSED` not overridden | `export GMAIL_LABEL_PROCESSED=evaluator/test-live` before invoking |
| Live Gmail test message lingers in inbox after a failed run | Cleanup teardown couldn't reach Gmail | Manually trash the `[TEST-LIVE-…]` message in the inbox |

## Adding new tests

- **New backend invariant?** Add a case to `test_rubric_schema.py` (for
  pydantic) or `test_settings_api.py` (for HTTP).
- **New form behavior?** Add a case to `tests/unit/settings-form.test.tsx`.
  These run in <100ms each and are the fastest way to lock down logic.
- **New page state or navigation?** Add a case to the matching e2e
  spec. Use `setMocks(...)` to inject the backend state, then assert on
  the rendered DOM.
- **New backend endpoint?** Add factories to `fixtures.ts`, add a key to
  the mock control vocab, and update the path-pattern matcher in
  `mock-server/server.mjs` if needed (already supports `:id`).
