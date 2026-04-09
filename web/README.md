# web/ — Dashboard

Next.js 15 App Router dashboard for the AI Candidate Evaluator.
Three pages: candidates list, candidate detail, settings (rubric editor).
Auth via email + password against an in-process test-user list.

## Quickstart (60 seconds)

```bash
cd web
cp .env.example .env.local       # set AUTH_SECRET (must match backend)
npm install
npm run dev                      # http://localhost:3100
```

Sign in with the pre-filled credentials:
- `admin@curator.local` / `curator`

The dashboard expects the FastAPI backend on `http://localhost:8000` by
default. Override with `BACKEND_URL` in `.env.local`.

## Want the full guide?

**See [FRONTEND.md](./FRONTEND.md)** for:

- Architecture (auth contract, server-side proxy, mock backend for tests)
- File map with what each component does
- Rubric editor — how the form maps to the backend schema
- How to add a new page / component / API call
- Test commands (Vitest unit + Playwright e2e + visual regression)
- Cross-browser run and how to update visual baselines
- Troubleshooting table for the common issues

## Test commands at a glance

```bash
npm test                                # Vitest unit tests       (47, ~1.4s)
npx playwright test                     # All browsers + visual   (99, ~96s)
npx playwright test --project=authenticated-chromium   # Chromium only (faster)
npx playwright test visual.spec.ts --update-snapshots  # Refresh baselines
```

Test runbook (all four tiers, including backend + live Gmail) is in
**[../TESTING.md](../TESTING.md)**.
