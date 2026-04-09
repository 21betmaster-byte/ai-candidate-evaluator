# Backend Status

Status snapshot of the `backend/` service for the AI Candidate Evaluator.
Last updated: 2026-04-08 (post hiring-manager-rubric work).

> **For the frontend dashboard, see [`../web/FRONTEND.md`](../web/FRONTEND.md).**
> **For the test runbook (all four tiers), see [`../TESTING.md`](../TESTING.md).**

## 1. Stack
- **FastAPI** + Uvicorn (ASGI), Python 3.11+
- **PostgreSQL** via SQLAlchemy ORM, **Alembic** migrations
- **Anthropic SDK** (Claude Sonnet 4.6 / Opus 4.6)
- **Playwright (headless Chromium)** for SPA portfolio fallback
- **PyMuPDF** for resume PDF text + link-annotation extraction
- **httpx + BeautifulSoup** for static portfolio scraping
- Deps managed in `pyproject.toml`

## 2. Data Models (`app/models.py`)
- **Candidate** — email, name, status (`pending`, `incomplete`, `manual_review`, `auto_pass`, `auto_fail`, `passed_manual`, `failed_manual`, `processing_error`), `current_evaluation_id`, `missing_items`, `last_inbound_message_id`
- **Evaluation** — FK→candidate, `superseded`, raw resume text + filename, github/portfolio URLs and fetched data (JSONB), structured profile, per-dimension scores, `overall_score`, `tier`, `decision_reason`
- **EmailLog** — direction, classification, gmail message id, sender, subject, body snippet, template used
- **Job** — type, payload (JSONB), status, attempts/max_attempts, `next_run_at`, `last_error`
- **ProcessingLog** — per-candidate timeline (step, level, message, meta)
- **AppSettings** — singleton (id=1): polling interval, **`rubric: list[RubricDimension]`** (the new shape — see §4.7a), tier thresholds, next-steps copy, reminder hours, company name
- Schema migrations:
  - `alembic/versions/0001_initial.py` — initial schema
  - `alembic/versions/0002_rubric_list.py` — converts the legacy
    `rubric_weights: dict[str,int]` column into the new
    `rubric: list[{key, description, weight}]` JSONB list. In-place
    backfill: each existing key gets a seeded description (for the
    four defaults) or an empty string (for unknown keys), then the
    old column is dropped. Reversible via `alembic downgrade`.

## 3. API Routes (`app/routes/`)
- `GET  /api/candidates` — list, filter by status, sort by score/created (max 500)
- `GET  /api/candidates/{id}` — detail with current evaluation + processing logs
- `POST /api/candidates/{id}/decision` — manual pass/fail override
- `POST /api/poll` — manual inbox poll trigger
- `GET  /api/settings` / `PUT /api/settings` — read/update singleton. Pydantic validates: rubric non-empty, unique keys, valid slug regex on each key, non-blank description (1–500 chars), weights sum to exactly 100, ordered thresholds (`auto_fail < manual_review < auto_pass`).
- `GET  /healthz`
- CORS enabled (configurable origin)

## 4. Pipeline Stages (`app/pipeline/`)

### 4.1 `classify.py` — Sonnet Call #1 (triage)
LLM triage of inbound email → `application` / `question` / `spam_sales` / `auto_reply` / `gibberish` / `other`. Heuristic shortcuts for auto-reply subject and empty body. Inputs to Sonnet: subject, sender, attachment filenames (not bytes), first 4,000 chars of body. Runs on `claude-sonnet-4-6`, `max_tokens=400`, SDK-default temperature.

### 4.2 `resume.py` — PDF parsing
- Extracts text via PyMuPDF `page.get_text("text")`.
- **Also extracts link-annotation URIs** via `page.get_links()` (`extract_pdf_link_uris`). This captures hyperlinked words like "LinkedIn"/"GitHub" that the text stream misses.
- Text URLs + annotation URLs are merged and deduped before being returned in `ParsedResume.urls`.
- Selects the first PDF attachment; returns `pdf_present=False` if none.

### 4.3 `extract.py` — URL helpers
- `find_urls()` regex over arbitrary text (strips trailing punctuation).
- `classify_urls()` returns `(github, portfolio, linkedin)` picking the first match of each category.
- `is_github_profile()`, `is_linkedin()`, `looks_like_portfolio()` heuristics.

### 4.4 `github.py` — GitHub fetcher
Fetches candidate's GitHub profile, top repos, and dependency manifests. Returns a `GitHubData` dataclass with:
- `username`, `profile_url`, `public_repos`, `followers`
- `languages: dict[str, int]` — **real byte counts** per language, aggregated across top repos via per-repo `/languages` calls
- `recent_repos_pushed_6mo: int` — repos with a push in the last 180 days
- `recent_commits_90d: int` — **real commits** authored by `username` in the last 90 days, via `/repos/{owner}/{repo}/commits?author=&since=` per top repo
- `top_repos: list[dict]` — each repo carries `name`, `stars`, `forks`, `language`, `description`, `url`, `pushed_at`, **`manifest_type`**, **`dependencies`**

**Manifest fetching (Alternative 2 strategy, ~2 calls per top repo):**
1. `GET /repos/{o}/{r}/contents/` — list root files.
2. Pick first supported manifest by priority: `package.json` → `pyproject.toml` → `requirements.txt` → `Cargo.toml` → `go.mod`.
3. Fetch that manifest and parse to a deduped list of **dependency names only** (no versions, no dev/peer split).

Parsers live in `github.py` itself: `_parse_package_json`, `_parse_pyproject`, `_parse_requirements_txt`, `_parse_cargo_toml`, `_parse_go_mod`. README fetching intentionally skipped (cost vs. signal).

Error separation: `GitHubCandidateError` (404/private → email candidate) vs `GitHubInfraError` (5xx/timeout → queue retry).

Worst-case API calls per candidate: ~10 top repos × (1 listing + 1 manifest + 1 languages + 1 commits) + 1 profile + 1 repos list = ~42. Well inside authenticated 5k/hr limit.

### 4.5 `portfolio.py` — Portfolio scraper
- First pass: `httpx` + BeautifulSoup.
- **SPA fallback**: if the static HTML returns < `SPA_LINK_THRESHOLD` (8) anchors OR < `SPA_TEXT_THRESHOLD` (800) chars of visible text, re-render with Playwright headless Chromium (`_render_with_playwright`). Falls through to static HTML if Playwright fails.
- Returns `PortfolioData(url, final_url, title, text_snippet, discovered_github_url, discovered_resume_url, discovered_resume_bytes, project_links)`.
- `text_snippet` capped at **20,000 chars** (bumped from 4k on 2026-04-08).
- Resume auto-download: if the page has an `<a>` tag pointing at a `.pdf` with "resume"/"cv" in the label or URL, fetches it (< 10 MB cap).
- `PortfolioCandidateError` vs `PortfolioInfraError` same pattern as GitHub.

### 4.6 `structure.py` — Sonnet Call #2 (extraction)
**The most important stage — this is the normalization layer the Opus scorer consumes.**

Called by `handlers.handle_structure_profile` with `(resume_text, github_data, portfolio_data)`.

**Pre-processing (deterministic, in Python):**
- `_strip_github_urls()` — removes `profile_url` and `top_repos[].url` so no URLs reach Sonnet.
- `_sanitize_portfolio()` — produces a compact dict with precomputed flags:
  - `has_downloadable_resume: bool` — true if `discovered_resume_url` is set.
  - `has_live_demos: bool` and `live_demo_count: int` — computed by `_compute_portfolio_flags()`:
    > *"A live demo is a project link whose hostname is different from the portfolio's own domain AND which is not GitHub, LinkedIn, Twitter/X, or a mailto/tel link. Counted by unique hostname."*
  - Excluded hosts: `github.com`, `linkedin.com`, `twitter.com`, `x.com` (+ `www.` variants). Own-domain detection includes subdomains.
- **Dict field ordering is load-bearing** for `_sanitize_portfolio()` — the dict emits `title`, `has_downloadable_resume`, `has_live_demos`, `live_demo_count` **before** `text_snippet`. JSON serialization preserves insertion order, and the downstream budget slices the tail — this guarantees the deterministic flags always survive truncation.

**Truncation budgets (chars, per input section):**
| Section | Budget | Rationale |
|---|---|---|
| Resume | 12,000 | ~3 pages of PyMuPDF text |
| GitHub JSON | 4,000 | stripped dict is small |
| Portfolio JSON | 20,000 | bumped from 4k on 2026-04-08; covers 2-4 case studies |

**LLM call parameters:**
- Model: `claude-sonnet-4-6`
- `max_tokens=2500`
- `temperature=0` (deterministic extraction)

**System prompt (`STRUCTURE_SYSTEM`, 4,054 chars):** extraction-only, not evaluation. Key rules:
- Omit fields you can't populate, never guess.
- Never invent metrics, products, skills.
- Extract ownership language verbatim — don't upgrade "we launched" to "I built".
- Duration fields verbatim, no calculation/rounding.
- **No URLs anywhere in the output** — evidence fields are text references like `"resume: Pazcare role"` or `"repo: melon-expense-tracker"`.
- **`headline` must be a direct quote** from the resume summary or portfolio title.
- `current_role` = `"no current role"` if none stated.
- `technical_skills` split into three parallel lists (no overlap computation):
  - `from_resume` — what the candidate listed
  - `from_github_languages` — detected from GitHub `languages` block
  - `from_github_manifests` — frameworks/libraries from dep manifests
- `shipped_products[]` includes `evidence_type` (`live_url | repo | screenshot | text_claim_only`), `stack_from_code[]`, `stack_source`.
- Final check: every metric traceable to a source line; every shipped product requires explicit ownership language.

**Output schema (selected highlights):**
```
{
  "name", "headline", "years_of_experience", "current_role",
  "work_experience": [{company, title, duration, highlights: []}],
  "technical_skills": {from_resume, from_github_languages, from_github_manifests},
  "shipped_products": [{name, description, evidence, evidence_type,
                        in_production, stack_from_code, stack_source}],
  "education": [],
  "github_signal": {active, primary_languages, notable_repos, activity_summary, total_public_repos},
  "portfolio_signal": {has_real_projects, project_count, highlights}
}
```

**Post-Sonnet merge (single source of truth):** after parsing Sonnet's JSON, `structure_profile()` overwrites `portfolio_signal.has_live_demos`, `live_demo_count`, and `has_downloadable_resume` with the Python-computed flags. Sonnet is explicitly told *not* to emit those keys — the deterministic flags are the only source of truth.

Parse failure fallback: returns `{"_parse_error": True, "_raw": raw[:2000]}`.

### 4.7 `score.py` — Opus Call (evaluation)
Rubric scoring on `claude-opus-4-6`. **The rubric is now hiring-manager-authored** — dimensions, descriptions, and weights all live in the database (`AppSettings.rubric`) and are edited from the dashboard's `/settings` page.

`score_candidate(profile, rubric)` takes the full list and renders it into the user message as:

```
RUBRIC (each dimension is authored by the hiring manager — use the
description as the authoritative definition of what to measure):
- technical_depth (weight: 35%)
    Description: Depth of hands-on engineering skill: shipping non-trivial systems …
- shipped_products (weight: 30%)
    Description: Evidence of owning and launching real products end-to-end …
…
```

The system prompt explicitly tells Opus to treat each description as the **authoritative definition** of the dimension and to score narrowly when the description is narrow. This is what lets a hiring manager invent dimensions like `design_taste` or `storytelling` without any code change.

Returns `{scores: {key: {score, reasoning}}, overall_score, decision_reason}`. Per-dimension scores are integers 0–100; the overall is the weighted mean. Out-of-range or non-int responses from Opus are clamped/coerced to 0 so a hallucinated `{"score": "eighty"}` never crashes the pipeline.

`compute_weighted(scores, rubric)` walks the rubric list (not the scores dict) so missing keys count as zero — defends against Opus omitting a dimension under load.

### 4.7a `RubricDimension` (`schemas.py`)

```python
class RubricDimension(BaseModel):
    key: str          # ^[a-z0-9][a-z0-9_]{0,63}$
    description: str  # 1–500 chars, non-blank, fed verbatim to Opus
    weight: int       # 0–100
```

Validation lives in pydantic so both the API route AND the underlying scoring code share one source of truth. Stored in `AppSettings.rubric` as a JSONB list.

`DEFAULT_RUBRIC` (in `models.py`) is a four-dimension seed with descriptions filled in (`technical_depth`, `shipped_products`, `business_thinking`, `speed_of_execution`) — used when nothing has been authored yet.

### 4.8 `decide.py` — Tier assignment
Thresholds from `AppSettings`: `≥70 → auto_pass`, `50–69 → manual_review`, `≤49 → auto_fail`.

### 4.9 `escalate.py`
Move candidate to `processing_error` after job retries exhausted.

## 5. Gmail Integration (`app/gmail/`)
- **`client.py`** — OAuth2 refresh-token auth, Gmail API v1 send/fetch, full MIME tree walk with attachment decoding into `Attachment(filename, mime_type, data)` dataclass. `InboundEmail` dataclass holds `message_id, thread_id, sender, sender_email, sender_name, subject, body_text, attachments, label_ids`.
- **`poller.py`** — lists unprocessed inbox messages, dedupes against `email_logs`, enqueues `ingest_email` jobs, applies processed label via Gmail.

## 6. Job Queue & Worker (`app/jobs/`)
- **`queue.py`** — Postgres queue using `SELECT … FOR UPDATE SKIP LOCKED`; `enqueue/claim_due/complete/fail_with_backoff`; exponential backoff (60s → 300s → 900s → 3600s), 5 max attempts.
- **`worker.py`** — `python -m app.jobs.worker`; polls every 5s, dispatches via `HANDLERS`, runs periodic inbox poll (default 2 min).
- **`handlers.py`** — 16 handlers chaining the pipeline: `ingest_email`, `classify`, `ack_email`, `parse_resume`, `fetch_github`, `fetch_portfolio`, `discover_secondary`, `structure_profile`, `score`, `decide`, `send_decision_email`, `send_template_email`, `send_reminder`, …
  - `fetch_github` handler persists the full `GitHubData` including the new `manifest_type`/`dependencies` per repo and the split `recent_repos_pushed_6mo`/`recent_commits_90d` fields into `evaluation.github_data`.

## 7. LLM Wrapper (`app/llm.py`)
```python
def _cached_system(system: str) -> list[dict]
def call_sonnet(system, user, max_tokens=2048, temperature=None) -> str
def call_opus(system, user, max_tokens=3000) -> str
def parse_json_block(text) -> dict
```
- **Prompt caching is enabled.** Every `system` prompt is wrapped in a `[{"type": "text", "text": ..., "cache_control": {"type": "ephemeral"}}]` block. Anthropic keeps a ~5-minute cache entry; repeat reads cost 1/10th the input-token price. Cache writes cost 1.25×, break-even at ~2 hits (trivially cleared within a batch).
- `temperature` is optional; when `None` the SDK default is used. `structure_profile` passes `temperature=0` for deterministic extraction. `classify_email` leaves it at default.
- Model IDs come from `settings.sonnet_model` / `settings.opus_model` (defaults: `claude-sonnet-4-6`, `claude-opus-4-6`).
- `parse_json_block` tolerates code fences and unbalanced preambles — extracts the first balanced `{...}`.

## 8. Email Templates (`app/emails/templates.py`)
17 brand-voice plain-text templates (acknowledgment, pass/fail decision, missing items, non-PDF attachment, question response, auto-reply bounce, spam rejection, …). `RenderedEmail` dataclass (subject, body, template_key). Guarantee: no numeric scores or rubric terms in candidate-facing copy.

## 9. Auth (`app/auth.py`)
- `require_user()` dependency. Empty `ALLOWED_EMAILS` = dev mode (reads `X-User-Email` or returns `"dev@local"`).
- Production: requires `Authorization: Bearer <jwt>`. Verifies HS256 signature against `NEXTAUTH_JWT_SECRET` via `python-jose`, extracts `email` claim, checks membership in `ALLOWED_EMAILS` (case-insensitive). Any failure → 401 `"not authorized"`.
- Dashboard contract (Auth.js v5): must share `AUTH_SECRET` = backend `NEXTAUTH_JWT_SECRET` and override `jwt.encode`/`jwt.decode` to emit a plain HS256 JWT (Auth.js v5 defaults to JWE, which is not supported). Full example in the `auth.py` docstring.

## 9a. Structured Logging (`app/logging_setup.py`)
End-to-end observability per PRD §3 and the Plum Builders' Residency brief
("ask the candidate to walk through the logs and explain what happened").

- `configure_logging()` — idempotent structlog + stdlib setup. JSON to stdout (Railway-friendly). Called from `main.py` startup and `worker.main()`.
- `log_event(db, candidate_id, step, message, level, meta)` — one-shot log that writes both (a) a structlog JSON line to stdout and (b) a `ProcessingLog` row to the DB (which the dashboard detail page renders). Never raises.
- `log_step(db, candidate_id, step, meta)` — context manager wrapping a pipeline step. Emits `started` + `completed` (or `failed`) rows with `duration_ms` and exception metadata captured automatically.
- Every PRD-required step is wrapped: `email_received`, `classify`, `ingest`, `parse_resume`, `fetch_github`, `fetch_portfolio`, `structure_profile`, `score`, `decide`, `send_email`.
- `queue.fail_with_backoff` emits `retry scheduled in Ns (attempt k/N)` warn-level rows and a final `retries exhausted` error row, so infra failures appear on the candidate timeline alongside domain events.
- `_adopt_orphan_logs` back-fills `candidate_id` on pre-candidate logs (email_received, classify) once the candidate row exists — matched by `meta.message_id` — so the dashboard shows the full timeline.

## 10. Tests (`backend/tests/`)

**56 hermetic tests** running in **~0.1s**, plus **4 opt-in live Gmail tests**. Full runbook in [`../TESTING.md`](../TESTING.md). Markers + opt-out config in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
markers = ["live: tests that hit real external services …"]
addopts = "-m 'not live'"
```

### Hermetic suite (default `pytest`)

- `test_score_compute.py` — weighted score math against a custom rubric list (3 cases)
- `test_decide.py` — tier boundary logic (5 cases)
- `test_extract.py` — URL find/classify, GitHub/LinkedIn detection (4 cases)
- `test_templates.py` — render guarantees: no scores/rubric leakage, name injection, list rendering (4 cases)
- `test_auth.py` — `require_user` dep: dev mode, missing/malformed bearer, wrong secret, empty secret, missing email claim, not-in-allowlist, happy path with case-normalization (9 cases)
- `test_structure_and_parsers.py` — manifest parsers for all 5 ecosystems, `_compute_portfolio_flags`, `_strip_github_urls`, `_sanitize_portfolio` ordering regression, `extract_pdf_link_uris` (17 cases)
- **`test_rubric_schema.py`** — pydantic-level validation of `RubricDimension` + `SettingsModel`. Locks down weights summing to 100, unique keys, slug regex, blank descriptions, weight bounds, custom dimension acceptance, dimension ordering. (27 cases)
- **`test_settings_api.py`** — `/api/settings` GET/PUT integration via FastAPI `TestClient`. Verifies the full HTTP round-trip including: persistence across requests, custom dimensions surviving the round-trip, threshold updates not stomping the rubric, every validation failure returning 4xx (never 500). (16 cases)
- **`test_score_prompt.py`** — Pins down the Opus contract: hiring-manager descriptions reach Opus verbatim, custom dimension keys round-trip, missing/out-of-range/non-int Opus responses degrade gracefully (not 500), reason length capped, `compute_weighted` math against custom rubrics. (10 cases)
- `test_e2e.py` — **full-pipeline end-to-end tests (13 cases)** driven against an in-memory sqlite DB with all external I/O (Gmail, GitHub, portfolio, LLM, PDF parsing) faked in `conftest.py`. Covers PRD §9 P0 flows: happy path, dashboard detail timeline + list endpoint, missing items, non-PDF attachment, gibberish, duplicate (superseded eval), GitHub 404, GitHub infra retry → eventual success, retries exhausted → processing_error, secondary discovery (GitHub in portfolio), concurrent applications (no cross-contamination), manual-review pass action, poll-now endpoint. Each test also asserts the corresponding ProcessingLog timeline entries exist with duration + meta, enforcing the PRD §3 logging acceptance criteria.
- `conftest.py` — shared fixtures: sqlite engine (JSONB→JSON shim applied before `app.models` imports), `FakeGmail`, `fake_parse_resume`, deterministic LLM/GitHub/portfolio fakes (`_fake_score` now takes `(profile, rubric)`), `drive_jobs(db)` queue driver, FastAPI `TestClient`.

### Live Gmail tests (`test_gmail_live.py`, opt-in)

4 cases that hit the real Gmail API using the OAuth refresh token. Default `pytest` invocation deselects them. Run with:

```bash
GMAIL_LABEL_PROCESSED=evaluator/test-live RUN_LIVE_TESTS=1 pytest -m live
```

- `TestGmailLiveOAuth.test_can_build_service_and_list_labels` — proves the refresh token still works.
- `TestGmailLivePolling.test_send_then_poll_then_fetch_then_mark_processed` — sends a unique-subject self-message, polls for it, fetches the parsed `InboundEmail`, marks processed, re-polls to confirm it's gone.
- `TestGmailLivePollerIntegration.test_poll_inbox_returns_count` — calls the higher-level `poll_inbox()` function (the same code path the production worker runs).
- `TestGmailLiveErrorPaths.test_fetch_nonexistent_message_raises` — verifies real Google API errors surface as `HttpError`, not silent None.

**Six safety properties** baked in (UUID-tagged subjects, self-send only, **module refuses to run unless `GMAIL_LABEL_PROCESSED` is overridden to a non-prod label**, try/finally trash cleanup, no full-pipeline runs, default-skipped). See the docstring at the top of `tests/test_gmail_live.py` for the full list.

Portfolio Playwright fallback is integration-only (needs Chromium) and intentionally not unit-tested — it's covered by the trace script.

## 11. Scripts (`backend/scripts/`)
- **`trace_email.py`** — runs the deterministic parsers (extract, resume, github, portfolio) against a hardcoded test email + local PDF and prints a processing-log-style trace. Skips LLM stages.
- **`show_sonnet_input.py`** — dumps the exact `system` + `user` payloads that `classify_email` and `structure_profile` would send to Sonnet, without calling the API. Uses the real `_strip_github_urls` and `_sanitize_portfolio` helpers so the output matches production.
- **`test_gmail.py`**, **`get_gmail_refresh_token.py`** — Gmail OAuth bootstrap.

## 12. Config & Deployment
- **`config.py`** — Pydantic `BaseSettings` from `.env`: `database_url`, `anthropic_api_key`, `gmail_*_token`, `github_token`, poll intervals, `allowed_emails`, `company_name`, `nextauth_jwt_secret`, `sonnet_model`, `opus_model`.
- **`Dockerfile`** — Python 3.11-slim, installs build tools + libpq, `pip install .`, then **`python -m playwright install --with-deps chromium`** for SPA fallback. Runs `alembic upgrade head && uvicorn app.main:app`; worker service overrides CMD to `python -m app.jobs.worker`.
- **`railway.json`** at repo root for Railway deploy.

## 13. Cost model (per candidate, prompt caching enabled)

Three LLM calls: `classify_email` (Sonnet, tiny) → `structure_profile` (Sonnet, the big one) → `score_candidate` (Opus).

| Component | Cost |
|---|---|
| `classify_email` (Sonnet, ~280 in + 100 out, sys cached) | ~$0.002 |
| `structure_profile` system (cached read, ~1k tok) | ~$0.0003 |
| `structure_profile` user input (fresh, ~6–11k tok depending on portfolio size) | ~$0.015–0.030 |
| `structure_profile` output (~2k tok) | ~$0.030 |
| `score_candidate` (Opus, ~4k in + 1k out, sys cached) | ~$0.135 |
| **Total** | **~$0.18–0.20** |

Opus dominates at ~74% of per-candidate cost. All three system prompts are marked with `cache_control: ephemeral` in `llm.py::_cached_system`, so the system-prompt portion drops to 10× cheaper on repeat reads within ~5 minutes.

## 14. Recent changes (2026-04-07 → 2026-04-08)

### Hiring-manager-authored rubrics (2026-04-08, evening)
- **`AppSettings.rubric_weights: dict[str,int]` → `rubric: list[RubricDimension]`** with `{key, description, weight}`. New pydantic model in `schemas.py` with strict validation: slug-key regex, non-blank descriptions, weights summing to exactly 100.
- **Migration `0002_rubric_list.py`** — in-place backfill, drops `rubric_weights`. Defaults seeded with descriptions for the four legacy dimensions; unknown keys backfilled with empty descriptions for the hiring manager to fill in.
- **`pipeline/score.py` rewritten** — `score_candidate(profile, rubric)` now takes the full list. New `_render_rubric()` helper renders each dimension as `- key (weight: N%)\n    Description: …` so Opus reads them cleanly. System prompt updated to instruct Opus to treat each description as the *authoritative definition* of the dimension. `compute_weighted` walks the rubric list (not the scores dict) so missing keys count as zero.
- **`handle_score`** updated to load `settings.rubric` (with `DEFAULT_RUBRIC` fallback) and pass it through. ProcessingLog meta records keys + weights only — descriptions kept out of the log.
- **3 new test files** — `test_rubric_schema.py` (27 cases), `test_settings_api.py` (16 cases), `test_score_prompt.py` (10 cases). All run in <0.1s.
- **Live Gmail tier added** — `test_gmail_live.py` with 4 opt-in tests, hidden behind `pytest -m live` and `GMAIL_LABEL_PROCESSED` override. Hits real Gmail safely (UUID-tagged subjects, self-send only, aggressive cleanup).
- **Backend test count: 33 → 56 hermetic** + 4 live = 60 total.

### Final pass (2026-04-08, afternoon)
- **Prompt caching** enabled in `llm.py`. `_cached_system()` wraps every system prompt in a `cache_control: ephemeral` block. Applied to both `call_sonnet` and `call_opus`.
- **`portfolio_signal` schema dedupe**: removed `has_live_demos` / `has_downloadable_resume` from the `STRUCTURE_SYSTEM` output schema. `structure_profile()` now overwrites those keys (plus `live_demo_count`) in Python after parsing Sonnet's response. Single source of truth = the precomputed flags.
- **Unit test suite** added: `tests/test_structure_and_parsers.py` with 17 offline tests. 33/33 total tests passing.
- Silenced Python 3.14 `re.split` positional-arg deprecation in `github.py::_strip_py_version_spec`.


### Parser hardening
- **PDF link-annotation extraction** added (`resume.py::extract_pdf_link_uris`). Captures hyperlinked words like "LinkedIn"/"GitHub" that `get_text()` misses.
- **Playwright SPA fallback** added (`portfolio.py::_render_with_playwright`). Triggered when static HTML returns < 8 anchors or < 800 chars of visible text. `pyproject.toml` + `Dockerfile` updated.

### GitHub fetcher rewrite
- `recent_commits_6mo` (wrong — it counted repos, not commits) split into:
  - `recent_repos_pushed_6mo` (what the old field actually measured)
  - `recent_commits_90d` (real per-repo `/commits?author=&since=` counts)
- `languages` field is now **real byte counts** from per-repo `/languages` endpoint, not repo counts.
- Added `manifest_type` + `dependencies` per top repo via **Alternative 2 strategy** (list root contents once, fetch first matching manifest). Parsers for 5 ecosystems.

### Sonnet Call #2 rewrite (`structure.py`)
- New `STRUCTURE_SYSTEM` prompt: extraction-only framing, strict anti-hallucination rules, headline-as-direct-quote, ownership-verbs-verbatim, no URLs anywhere in output.
- `technical_skills` split into `from_resume` / `from_github_languages` / `from_github_manifests`. No overlap computation — Opus handles that.
- `_strip_github_urls()` removes `profile_url` and `top_repos[].url` before serialization.
- `_sanitize_portfolio()` precomputes `has_live_demos`, `live_demo_count`, `has_downloadable_resume` in Python so they're deterministic.
- **Portfolio dict field ordering** pinned: small flags before `text_snippet` so tail-chopping never strips them.
- **Portfolio truncation bumped from 4k → 20k chars** (both in `portfolio.py` upstream cap and `structure.py` downstream slice).
- `temperature=0` added to `call_sonnet()` signature and used for the extraction call. `classify_email` unchanged.

### Documentation & scripts
- `scripts/trace_email.py` for deterministic parser tracing.
- `scripts/show_sonnet_input.py` for dumping exact LLM payloads without calling the API.

## 15. Known TODOs
None open.

### Intentionally not doing
- **Raising resume (12k) and GitHub (4k) truncation budgets preemptively** — current limits cover median candidates. Runtime logs will tell us when something actually gets cut off.
- **Adding more manifest ecosystems** (`Gemfile`, `pom.xml`, `build.gradle`, `composer.json`, `mix.exs`, `pubspec.yaml`, `Package.swift`) — add on demand if a real candidate hits `manifest_type: null` despite having a recognized manifest at root.

## Summary
End-to-end email-driven candidate screening backend: Gmail ingest → classify → resume/GitHub/portfolio scrape → LLM structuring & scoring → tier decision → templated reply. Async Postgres job queue with retries, full processing audit log, **hiring-manager-authored rubric** (key + description + weight) editable in the dashboard and passed verbatim to Opus. The `structure_profile` Sonnet call is the canonical normalization step — deterministic (temperature=0), URL-free, with precomputed portfolio flags and real dependency stacks from GitHub manifests. Backend test suite: 56 hermetic + 4 live Gmail (opt-in). Frontend dashboard: see [`../web/FRONTEND.md`](../web/FRONTEND.md).
