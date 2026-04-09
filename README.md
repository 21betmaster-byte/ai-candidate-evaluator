# AI Candidate Evaluator

## The Problem

Screening inbound job applications is one of the most time-consuming bottlenecks in hiring. A hiring manager receives dozens of emails with resumes, GitHub profiles, and portfolio links — then manually opens each attachment, cross-references work history against role requirements, checks GitHub for real shipping signal, reviews portfolio quality, and drafts a personalized response. This process takes 15-30 minutes per candidate, is prone to inconsistency (different reviewers weight different things), and creates a poor candidate experience when responses are slow or generic.

For small teams that can't afford a dedicated recruiting function, this means either burning engineering or founder time on screening, or letting strong candidates slip through the cracks because nobody got to their email fast enough.

## The Solution

An autonomous email agent that handles the entire candidate screening workflow end-to-end: from receiving the application email to sending a personalized pass/fail decision — with zero human intervention for clear-cut cases, and smart escalation for borderline ones.

**What it does:**
- **Monitors a Gmail inbox** for inbound applications and automatically processes new emails
- **Parses resumes** (PDF/DOCX), extracts structured data, and handles messy real-world inputs (multi-column layouts, non-English text, scanned documents)
- **Fetches external signals** — GitHub repos, contribution history, languages used; portfolio/project sites with SPA-aware scraping via headless Chromium
- **Evaluates candidates against a hiring-manager-defined rubric** using a two-model architecture: Claude Sonnet structures the raw data, Claude Opus scores it against weighted dimensions the hiring manager defines (e.g. "technical depth", "shipped products", "design taste")
- **Sends personalized email responses** — acceptance with next steps, rejection with specific constructive feedback, or a request for missing materials
- **Escalates ambiguous cases** to human review with full context, rather than making a bad automated call
- **Exposes a dashboard** where the hiring manager can review candidates, edit the scoring rubric, override decisions, and trigger inbox polling on demand

**Why it matters:** A hiring manager defines their rubric once in the dashboard (what matters, how much each dimension weighs), and the agent handles everything else. New candidates get evaluated in minutes instead of days, with consistent scoring against the same criteria every time. The hiring manager only spends time on the cases that genuinely need human judgment.

Built for the [Plum Builder's Residency](plum_builders_residency_brief.md) exercise — a 5-day sprint to build an agent that handles a real communication channel and automates a business workflow, tested live with real inputs.

## Architecture

A FastAPI backend on Railway polls a Gmail inbox at a configurable
interval. Each new message is enqueued in a Postgres-backed `jobs` table;
an asyncio worker (same image, different start command) claims jobs with
`SELECT ... FOR UPDATE SKIP LOCKED` and runs them through a step-wise
pipeline: `ingest → classify → parse_resume → fetch_github →
fetch_portfolio → discover_secondary_sources → structure (Sonnet) →
score (Opus) → decide → send_decision_email`. Each step is a separate
job row, so transient failures (GitHub 5xx, portfolio timeouts) retry
independently with exponential backoff (1m → 5m → 15m → 1h → escalate to
`processing_error`) without losing partial progress. A Next.js dashboard
(Auth.js v5 + HS256-JWT-shared-with-the-backend) reads from the same
Postgres via a server-side proxy and exposes a manual-review surface, a
**hiring-manager-authored rubric editor**, and a Poll-Now button.

## What's new — hiring-manager-authored rubrics

The rubric used to be a hardcoded `{technical_depth: 35, ...}` dict. It's
now a list of dimensions:

```json
[
  { "key": "technical_depth",   "description": "...", "weight": 35 },
  { "key": "shipped_products",  "description": "...", "weight": 30 },
  { "key": "design_taste",      "description": "...", "weight": 35 }
]
```

Hiring managers author this in `/settings`. Weights must sum to 100.
**Descriptions are passed verbatim to Opus** as the authoritative
definition of each dimension, so a hiring manager can invent
`design_taste` or `storytelling` and Opus will score against it without
any code change. Sonnet still does the structural extraction; Opus does
the evaluation.

Backend schema lives in `backend/app/schemas.py::SettingsModel`.
Migration is `backend/alembic/versions/0002_rubric_list.py` (in-place
backfill of legacy `rubric_weights` → new `rubric` list).

## Tech stack & rationale

- **Python + FastAPI** — fast to ship, great Pydantic validation, good
  fit for background jobs.
- **Postgres on Railway** — single managed dependency. Doubles as job
  queue (no Redis).
- **Postgres-backed jobs table** — chose this over RQ/Celery so retries
  are durable across restarts without paying for an extra Redis service.
  `SKIP LOCKED` gives safe concurrency.
- **Sonnet for structuring, Opus for scoring** — cheap fast model
  normalizes the messy raw inputs; the more capable model only sees
  clean structured data and the rubric.
- **PyMuPDF** — fastest reliable PDF text extraction in Python.
- **Next.js 15 App Router + Auth.js v5** — server components let us do
  the backend fetch + render in one round-trip. HS256 JWT shared with
  FastAPI keeps the auth contract simple.
- **Email/password auth (no Google)** — internal platform; test users
  hardcoded in `web/auth.ts`. Easy to swap to a real IdP later.

## Repo layout

```
ai_candidate_evaluator/
├── backend/                  FastAPI + worker + pipeline (Python)
│   ├── app/                  application code
│   ├── alembic/              database migrations (incl. 0002_rubric_list)
│   ├── tests/                pytest suite — 56 hermetic + 4 live Gmail
│   ├── BACKEND_STATUS.md     architecture deep-dive
│   ├── Dockerfile            Railway image
│   └── pyproject.toml
├── web/                      Next.js 15 dashboard (TypeScript)
│   ├── src/app/              App Router pages + API routes
│   ├── src/components/       Client + server components
│   ├── src/lib/              Typed backend client
│   ├── tests/unit/           Vitest — 47 component tests
│   ├── tests/e2e/            Playwright — 99 cross-browser + visual
│   ├── README.md             quickstart
│   └── FRONTEND.md           detailed frontend guide  ← start here
├── stitch/                   Original HTML mockups (reference only)
├── TESTING.md                Test runbook for all four tiers
├── PRD_AI_Candidate_Evaluator_V1.md
└── railway.json              Railway deploy (backend only)
```

## Local dev — backend

```bash
cd backend
cp .env.example .env          # fill in keys (Anthropic, Gmail OAuth, etc.)
python -m venv .venv && source .venv/bin/activate
pip install -e .[dev]
docker run -d --name pg -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:16
alembic upgrade head          # picks up 0002_rubric_list
# In one terminal:
uvicorn app.main:app --reload
# In another:
python -m app.jobs.worker
```

Trigger an inbox poll manually:
```bash
curl -X POST http://localhost:8000/api/poll -H 'X-User-Email: dev@local'
```

## Local dev — dashboard

See `web/FRONTEND.md` for the full guide. Short version:

```bash
cd web
cp .env.example .env.local    # set AUTH_SECRET (must match backend NEXTAUTH_JWT_SECRET)
npm install
npm run dev                   # http://localhost:3100
```

Sign in with the pre-filled test credentials:
- `admin@curator.local` / `curator`
- `shivam@curator.local` / `curator`

Edit `web/auth.ts` to add or remove users.

## Tests — four tiers

| Tier                          | Runner          | Tests | Wall time | Default? |
|-------------------------------|-----------------|-------|-----------|----------|
| Backend (hermetic)            | pytest          | 56    | ~0.1s     | ✅       |
| Backend (live Gmail)          | pytest -m live  | 4     | ~30s      | opt-in   |
| Frontend unit                 | Vitest          | 47    | ~1.4s     | ✅       |
| End-to-end (3 browsers + visual) | Playwright   | 99    | ~96s      | ✅       |
| **Default total**             |                 | **202** | **~98s** |          |

Demo-day checklist (run from the repo root):
```bash
cd backend && source .venv/bin/activate && pytest -q && cd ..
cd web && npm test && npx playwright test && cd ..
```

Plus the live Gmail tier before any deploy:
```bash
cd backend && source .venv/bin/activate && \
  GMAIL_LABEL_PROCESSED=evaluator/test-live RUN_LIVE_TESTS=1 \
  pytest -m live -q
```

Full instructions are in **[TESTING.md](TESTING.md)**.

## What I'd improve with more time

- Replace Gmail polling with Pub/Sub push notifications via Gmail watch
  — trades polling latency for true real-time.
- **Per-role rubrics** (currently a single global rubric). The schema
  was designed with this in mind — a `Role` table with a FK from
  `Candidate` and a per-role `rubric` JSONB is a small migration.
- Background reprocessing of `processing_error` candidates from the
  dashboard with one click.
- Real evals on the classifier and scorer with a labeled set
  (PRD §10 metrics).
- Streaming logs to the dashboard via SSE so you can watch a candidate
  get evaluated live.
- Mobile viewport visual baselines (currently desktop 1280×800 only).
- Replace the test-user credential list with a real IdP (Google,
  Workspace SAML) once we have more than a handful of users.

## Conscious trade-offs

- **Resume PDFs only.** Scanned/OCR PDFs are out of scope (PRD §B). The
  non-PDF path emails the candidate to re-send.
- **Email/password auth instead of Google SSO.** Internal platform; the
  Auth.js HS256 contract makes swapping the provider a 10-line change.
- **One worker process.** SKIP LOCKED supports many; one is plenty.
- **No reprocessing of past evaluations on settings change** (per
  PRD §7). Old scores are preserved as-is. *Note: this means editing
  the rubric does NOT re-score existing candidates — only new
  candidates get the new rubric.*
- **Rubric is global, not per-role.** Schema is ready for per-role; UI
  isn't. One rubric is enough for the residency.
- **Visual regression baselines are desktop only** (1280×800). Mobile
  responsiveness is enforced by Tailwind, not by tests.

## Help

- Backend deep dive: `backend/BACKEND_STATUS.md`
- Frontend deep dive: `web/FRONTEND.md`
- Test runbook: `TESTING.md`
- Product requirements: `PRD_AI_Candidate_Evaluator_V1.md`
- Original brief: `plum_builders_residency_brief.md`
