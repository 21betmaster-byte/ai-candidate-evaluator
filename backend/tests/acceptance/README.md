# Acceptance test fixtures

End-to-end fixtures for the AI Candidate Evaluator. One JSON manifest →
real `.eml` files with real PDF / DOCX attachments → uploaded into Gmail via
`users.messages.insert` so the existing poller picks them up.

## Layout

```
acceptance/
├── scenarios.json        # source of truth: 52 scenarios + resume content
├── build_fixtures.py     # renders scenarios.json → out/emails/*.eml
├── ingest_gmail.py       # uploads out/emails/*.eml via Gmail API
├── fixtures/             # user-supplied files (scanned PDFs, etc.)
└── out/
    └── emails/           # generated .eml files, one per scenario
```

## Workflow

```bash
cd backend/tests/acceptance

# 1. Generate all .eml files
python build_fixtures.py

# 2. (Optional) Drop in any hand-crafted fixtures the generator can't synthesize
#    — currently only B14 scanned PDF. See "User-supplied fixtures" below.

# 3. Upload everything into Gmail (applies label "acceptance" for cleanup)
python ingest_gmail.py

# 4. Let the poller run, then inspect the dashboard.

# 5. Clean up when done
python ingest_gmail.py --purge-label acceptance
```

Subsetting works everywhere via `--only`:

```bash
python build_fixtures.py --only A01,B14,D40
python ingest_gmail.py  --only A,E         # whole groups work too
```

## Scenario ID convention

`{GROUP}{NUMBER}_{slug}` — e.g. `B14_scanned_pdf`, `D42_pdf_metadata_injection`.
Groups match the approved plan:

- **A** — Happy-path / scoring tiers
- **B** — Resume content edge cases
- **C** — Attachment / delivery edge cases
- **D** — Prompt injection
- **E** — Duplicate / re-submission (dashboard state only)
- **F** — Rubric / config interactions
- **G** — PII / privacy sanity

Each scenario's `expected` block describes the first-half-of-flow assertions
(dashboard `status`, `missing_items`, optional `tier`). Scoring tier assertions
rely on recorded Sonnet/Opus responses — no live LLM calls.

## User-supplied fixtures

These scenarios need a file you can't (or shouldn't) synthesize:

| Scenario | Expected file | How to produce |
|---|---|---|
| `B14_scanned_pdf` | `fixtures/scanned_resume.pdf` | Take any generated PDF (e.g., `out/emails/` → extract an attachment, or use `jane_park_resume.pdf`), print it, rescan it, save as PDF. Must contain no extractable text. |

Scenarios marked `needs_user_fixture: true` in `scenarios.json` are silently
skipped by `build_fixtures.py` until the file exists — no error, just a
`SKIP:` line on stderr.

## Prerequisites for orchestrated scenarios

A few scenarios describe a flow that spans more than one email. The
generator emits only the "main" email; your test harness is responsible for
the orchestration:

| Scenario | Orchestration |
|---|---|
| `E45_duplicate_complete_resubmit` | Ingest a prior complete application from the same sender first |
| `E46_duplicate_after_incomplete` | Ingest a prior incomplete (no-attachment) email first |
| `E48_worse_resubmission` | Ingest a stronger prior resume first |
| `F50_rubric_reconfigured_midflight` | Pause pipeline after structuring, mutate settings, resume |
| `C37_resume_in_portfolio_page` | Stub portfolio fetch to return a page containing a downloadable resume link |

## Attachment kinds (what `build_fixtures.py` knows how to render)

| Kind | Output | Used by |
|---|---|---|
| `pdf` | Single-column PDF from `resume_content[key]` | most happy-path scenarios |
| `pdf_two_column` | Two-column layout | B13 |
| `pdf_long` | N-page PDF | B17 |
| `pdf_tables` | Table-heavy content | B22 |
| `pdf_hidden_text` | White-on-white hidden text | D41 |
| `pdf_annot_links` | Hyperlink annotations with anchor text vs URI | B08, D43 |
| `pdf_injection_metadata` | Injection in /Author metadata | D42 |
| `pdf_encrypted` | AES-256 encrypted | B15 |
| `pdf_corrupted` | Truncated/mangled bytes | B16 |
| `pdf_huge` | ~12MB via embedded padding blob | C35 |
| `pdf_raw_bytes` | Arbitrary bytes (`bytes_hex`) | C34 (zero-byte) |
| `pdf_wrong_ext` | DOCX bytes named `.pdf` | C33 |
| `docx` | Minimal OOXML | C31, C32 |
| `file_raw` | Any bytes + any MIME | C38 (.pages, .rtf, .txt, .odt) |
| `zip_with_pdf` | .zip containing a rendered PDF | C39 |
| `fixture` | User-supplied file from `fixtures/` | B14 |

To add a new kind, add a branch in `build_attachment()` in `build_fixtures.py`.

## Gmail insert mechanics

`ingest_gmail.py` uses:

```python
service.users().messages().insert(
    userId="me",
    internalDateSource="dateHeader",  # respect Date: header in .eml
    body={"raw": base64url(eml_bytes), "labelIds": ["INBOX", "UNREAD", <acceptance>]},
)
```

`insert` (not `import`) is the right verb: it skips SPF/DKIM evaluation and
never leaves the server, so we can freely use `@example.com` sender addresses
without bouncing. Messages land in INBOX with UNREAD so the existing
unread-based poller picks them up naturally.

## Extending

- Add a new scenario: append an entry to `scenarios.json` (reuse an existing
  resume_key or add a new block to `resume_content`).
- Add a new resume variant only: add a key to `resume_content` and reference
  it from an existing scenario's `resume_key`.
- No code changes needed for the common path — the generator is data-driven.
