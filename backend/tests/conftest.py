"""Test fixtures for the end-to-end pipeline.

Design notes
------------
- **Database**: in-memory SQLite (shared across threads via StaticPool). The
  production schema uses Postgres JSONB everywhere; we monkey-patch
  `sqlalchemy.dialects.postgresql.JSONB` to the generic `JSON` type BEFORE
  `app.models` is imported. SQLAlchemy then emits `JSON` DDL on sqlite and
  handles (de)serialization natively. This must happen at the top of
  conftest, before any `app.*` import touches models.

- **Queue driver**: the production worker uses `FOR UPDATE SKIP LOCKED` which
  sqlite can't do. `drive_jobs` is a simple ORM-only replacement that mirrors
  `worker.run_one_job` semantics (handle → complete OR fail_with_backoff →
  escalate on exhaustion). It also zeros `next_run_at` after each retry so
  tests don't have to wait for real backoff delays.

- **External calls**: every external I/O is replaced by a fake in the
  `mocked_externals` autouse fixture. Gmail, GitHub, portfolio, resume parsing,
  classify/structure/score LLMs — all deterministic. Individual tests can
  override any of these via `monkeypatch.setattr` on the handlers module.
"""
from __future__ import annotations

# ---- JSONB → JSON shim (must run before app.models import) ----
from sqlalchemy import JSON as _GenericJSON  # noqa: E402
import sqlalchemy.dialects.postgresql as _pg  # noqa: E402
_pg.JSONB = _GenericJSON  # type: ignore[attr-defined]

import os  # noqa: E402

# Ensure config loads with empty allowlist = dev auth mode for API tests
os.environ.setdefault("ALLOWED_EMAILS", "")
os.environ.setdefault("DATABASE_URL", "sqlite://")

from datetime import datetime, timezone  # noqa: E402
from typing import Any, Callable, Iterator  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

# Now import the app — models will use the shimmed JSONB=JSON
import app.db as app_db  # noqa: E402
from app.db import Base  # noqa: E402
import app.models as models  # noqa: E402
from app.models import (  # noqa: E402
    AppSettings,
    Candidate,
    DEFAULT_RUBRIC,
    DEFAULT_THRESHOLDS,
    EmailLog,
    Evaluation,
    Job,
    ProcessingLog,
)


# ---------------------------- Engine / session ----------------------------

_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    future=True,
)
_TestingSession = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)

# Redirect production session factories to the in-memory engine BEFORE any
# handler imports bind their own references.
app_db.engine = _engine
app_db.SessionLocal = _TestingSession

# Re-bind references that may already have been captured at import time.
import app.jobs.handlers as handlers_mod  # noqa: E402
import app.jobs.queue as queue_mod  # noqa: E402

handlers_mod.SessionLocal = _TestingSession


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.create_all(_engine)
    yield
    Base.metadata.drop_all(_engine)


@pytest.fixture()
def db() -> Iterator[Session]:
    """A fresh session wired to the in-memory DB, with per-test cleanup."""
    s = _TestingSession()
    try:
        yield s
    finally:
        s.rollback()
        s.close()
    # Wipe tables between tests so assertions stay isolated.
    with _engine.begin() as conn:
        for tbl in reversed(Base.metadata.sorted_tables):
            conn.exec_driver_sql(f"DELETE FROM {tbl.name}")


@pytest.fixture()
def settings_row(db: Session) -> AppSettings:
    row = AppSettings(
        id=1,
        polling_minutes=2,
        # DEFAULT_RUBRIC is a list of dimension dicts; JSONB column takes it verbatim.
        rubric=[dict(d) for d in DEFAULT_RUBRIC],
        tier_thresholds=dict(DEFAULT_THRESHOLDS),
        pass_next_steps_text="We'll reach out with next steps.",
        reminder_hours=48,
        company_name="Plum",
    )
    db.merge(row)
    db.commit()
    return row


# ---------------------------- Fake Gmail ----------------------------


class FakeGmail:
    """In-memory Gmail stand-in. Tests `deliver(...)` a message, the pipeline
    calls `list_unprocessed_messages()` / `fetch_email(id)` / `mark_processed(id)`,
    and outbound `send_email(...)` is captured in `sent`."""

    def __init__(self) -> None:
        self.inbox: dict[str, Any] = {}  # message_id -> InboundEmail
        self.processed: set[str] = set()
        self.sent: list[dict[str, Any]] = []
        self._seq = 0

    def deliver(self, email: Any) -> str:
        self.inbox[email.message_id] = email
        return email.message_id

    # ---- production API surface ----
    def fetch_email(self, message_id: str):
        return self.inbox[message_id]

    def list_unprocessed_messages(self) -> list[str]:
        return [mid for mid in self.inbox if mid not in self.processed]

    def mark_processed(self, message_id: str) -> None:
        self.processed.add(message_id)

    def send_email(self, to: str, body_text: str, in_reply_to=None, thread_id=None) -> str:
        self._seq += 1
        msg_id = f"out-{self._seq}"
        self.sent.append({
            "message_id": msg_id,
            "to": to,
            "body": body_text,
        })
        return msg_id


def _make_inbound(
    message_id: str,
    sender_email: str,
    sender_name: str | None,
    subject: str,
    body_text: str,
    attachments: list | None = None,
):
    from app.gmail.client import InboundEmail
    return InboundEmail(
        message_id=message_id,
        thread_id=f"thr-{message_id}",
        sender=f"{sender_name or ''} <{sender_email}>",
        sender_email=sender_email,
        sender_name=sender_name,
        subject=subject,
        body_text=body_text,
        attachments=attachments or [],
        label_ids=[],
    )


def _pdf_attachment(filename: str = "resume.pdf") -> Any:
    from app.gmail.client import Attachment
    return Attachment(filename=filename, mime_type="application/pdf", data=b"%PDF-fake")


def _docx_attachment(filename: str = "resume.docx", text: str = "Jane Doe resume\nLinkedIn: https://linkedin.com/in/jane") -> Any:
    """Build a real minimal .docx so the parser path is actually exercised."""
    from app.gmail.client import Attachment
    import io
    import docx as _docx

    doc = _docx.Document()
    for line in text.splitlines():
        doc.add_paragraph(line)
    buf = io.BytesIO()
    doc.save(buf)
    return Attachment(
        filename=filename,
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        data=buf.getvalue(),
    )


# ---------------------------- Fake parse_resume ----------------------------


class FakeParsedResume:
    def __init__(self, resume_present: bool, any_attachment: bool, text: str = "", urls=None, filename=None):
        self.resume_present = resume_present
        self.any_attachment = any_attachment
        self.text = text
        self.urls = list(urls or [])
        self.selected_filename = filename
        # Logging fields
        self.file_format = "pdf" if resume_present else None
        self.text_length = len(text)
        self.url_count_from_text = len(self.urls)
        self.url_count_from_annotations = 0
        self.parse_errors = None


def fake_parse_resume_factory(text="Jane Doe — Senior Engineer\n5 years experience", urls=None):
    def _inner(attachments):
        if not attachments:
            return FakeParsedResume(False, False, "", [], None)
        DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        supported = [
            a for a in attachments
            if (a.mime_type == "application/pdf" or (a.filename or "").lower().endswith(".pdf")
                or a.mime_type == DOCX_MIME or (a.filename or "").lower().endswith(".docx"))
        ]
        if not supported:
            return FakeParsedResume(False, True, "", [], None)
        return FakeParsedResume(True, True, text, list(urls or []), supported[0].filename)
    return _inner


# ---------------------------- Fake externals ----------------------------


def _fake_classify(email):
    """Default classifier: attachment implies application, keyword-based routing
    otherwise. Tests override as needed."""
    body = (email.body_text or "").lower()
    subj = (email.subject or "").lower()
    if "out of office" in subj or "automatic reply" in subj:
        return {"category": "auto_reply", "reason": "", "question_text": "", "heuristic_shortcut": "auto_reply_subject"}
    if any(k in body for k in ("asdfasdf", "qwerty", "lorem ipsum random")):
        return {"category": "gibberish", "reason": "", "question_text": ""}
    if "buy our product" in body or "sponsored" in body:
        return {"category": "spam_sales", "reason": "", "question_text": ""}
    if body.strip().endswith("?") and "salary" in body:
        return {"category": "question", "reason": "", "question_text": body[:200]}
    if email.attachments or "apply" in body or "application" in body or "resume" in body:
        return {"category": "application", "reason": "", "question_text": "", "confidence": 0.0}
    return {"category": "other", "reason": "", "question_text": ""}


class _FakeGitHubData:
    def __init__(self, username="janedoe"):
        self.username = username
        self.profile_url = f"https://github.com/{username}"
        self.public_repos = 12
        self.followers = 34
        self.languages = {"Python": 60, "TypeScript": 40}
        self.recent_repos_pushed_6mo = 5
        self.recent_commits_90d = 42
        self.top_repos = [{"name": "cool-app", "stars": 10, "description": "a thing"}]


class _FakePortfolioData:
    def __init__(
        self,
        url="https://example.com",
        discovered_github=None,
        discovered_resume_bytes=None,
        discovered_resume_url=None,
    ):
        self.url = url
        self.final_url = url
        self.title = "Jane Doe Portfolio"
        self.text_snippet = "Jane ships production software."
        self.project_links = ["https://example.com/proj1", "https://example.com/proj2"]
        self.discovered_github_url = discovered_github
        self.discovered_resume_bytes = discovered_resume_bytes
        self.discovered_resume_url = discovered_resume_url


def _fake_structure(resume_text, github_data, portfolio_data):
    return {
        "name": "Jane Doe",
        "summary": "Senior engineer who ships.",
        "technical_signals": ["Python", "Postgres"],
        "shipped_products": ["cool-app"],
        "_llm_meta": {"llm_model": "test", "llm_input_tokens": 0, "llm_output_tokens": 0,
                      "llm_cache_read_tokens": 0, "llm_cache_creation_tokens": 0, "llm_duration_ms": 0},
        "_extraction_stats": {"has_name": True, "has_headline": False, "years_of_experience": None,
                              "work_experience_count": 0, "shipped_products_count": 1,
                              "education_count": 0, "has_github_signal": False,
                              "has_portfolio_signal": False, "portfolio_flags_overridden": False},
    }


def _fake_score(profile, rubric):
    return {
        "scores": {
            "technical_depth": {"score": 80, "reasoning": "solid stack"},
            "shipped_products": {"score": 75, "reasoning": "cool-app"},
            "business_thinking": {"score": 70, "reasoning": "thoughtful"},
            "speed_of_execution": {"score": 72, "reasoning": "recent activity"},
        },
        "overall_score": 75.5,
        "decision_reason": "Strong fit across all rubric dimensions.",
        "_llm_meta": {"llm_model": "test", "llm_input_tokens": 0, "llm_output_tokens": 0,
                      "llm_cache_read_tokens": 0, "llm_cache_creation_tokens": 0, "llm_duration_ms": 0},
        "_clamped_dimensions": [],
    }


@pytest.fixture()
def gmail_fake() -> FakeGmail:
    return FakeGmail()


@pytest.fixture(autouse=True)
def mocked_externals(monkeypatch, gmail_fake: FakeGmail):
    """Replace all external I/O with deterministic fakes. Tests can still
    override individual pieces via their own monkeypatch calls."""
    import app.gmail.client as gmail_client

    monkeypatch.setattr(gmail_client, "fetch_email", gmail_fake.fetch_email)
    monkeypatch.setattr(gmail_client, "list_unprocessed_messages", gmail_fake.list_unprocessed_messages)
    monkeypatch.setattr(gmail_client, "mark_processed", gmail_fake.mark_processed)
    monkeypatch.setattr(gmail_client, "send_email", gmail_fake.send_email)

    # Pipeline fakes — patch on the handlers module because handlers did
    # `from ... import fetch_github`.
    monkeypatch.setattr(handlers_mod, "classify_email", _fake_classify)
    monkeypatch.setattr(handlers_mod, "parse_resume", fake_parse_resume_factory())
    monkeypatch.setattr(handlers_mod, "fetch_github", lambda url: _FakeGitHubData())
    monkeypatch.setattr(handlers_mod, "fetch_portfolio", lambda url: _FakePortfolioData())
    monkeypatch.setattr(handlers_mod, "structure_profile", _fake_structure)
    monkeypatch.setattr(handlers_mod, "score_candidate", _fake_score)

    # Also patch call_sonnet/call_opus in case anything bypasses the pipeline layer.
    import app.llm as llm_mod
    monkeypatch.setattr(llm_mod, "call_sonnet", lambda *a, **kw: '{"category":"other","reason":"","question_text":""}')
    monkeypatch.setattr(llm_mod, "call_opus", lambda *a, **kw: '{}')
    yield


# ---------------------------- Queue driver ----------------------------


def drive_jobs(db: Session, max_iterations: int = 50) -> int:
    """Drain the job queue synchronously. Mirrors worker.run_one_job but with
    ORM-only claim (sqlite has no SKIP LOCKED) and no backoff sleeping.

    Returns the number of jobs that were executed (including retries). Stops
    when no more due jobs remain or max_iterations is reached."""
    from app.pipeline.escalate import escalate_processing_error

    executed = 0
    for _ in range(max_iterations):
        pending = (
            db.query(Job)
            .filter(Job.status == "pending", Job.next_run_at <= datetime.now(timezone.utc))
            .order_by(Job.next_run_at)
            .limit(5)
            .all()
        )
        if not pending:
            break
        for job in pending:
            job.status = "running"
            db.add(job)
            db.commit()
            handler = handlers_mod.HANDLERS.get(job.type)
            executed += 1
            if handler is None:
                queue_mod.fail_with_backoff(db, job, f"no handler for {job.type}")
                continue
            try:
                handler(db, job)
                queue_mod.complete(db, job)
            except Exception as e:
                exhausted = queue_mod.fail_with_backoff(db, job, repr(e))
                if exhausted:
                    escalate_processing_error(db, job)
                else:
                    # Fast-forward the retry so drive_jobs picks it up next pass.
                    job.next_run_at = datetime.now(timezone.utc)
                    db.add(job)
                    db.commit()
    return executed


@pytest.fixture()
def run_pipeline(db: Session) -> Callable[..., int]:
    def _run(max_iterations: int = 50) -> int:
        return drive_jobs(db, max_iterations=max_iterations)
    return _run


# ---------------------------- FastAPI TestClient ----------------------------


@pytest.fixture()
def client(db: Session) -> Iterator[TestClient]:
    from app.main import app
    from app.db import get_db

    # Tables are already created by the _schema fixture via
    # Base.metadata.create_all(). Skip Alembic migrations at startup because
    # they emit Postgres-specific DDL (e.g. '{}'::jsonb) that SQLite rejects.
    os.environ["SKIP_STARTUP_MIGRATIONS"] = "1"

    def _override_get_db():
        s = _TestingSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    os.environ.pop("SKIP_STARTUP_MIGRATIONS", None)


# ---------------------------- Helpers exposed to tests ----------------------------


@pytest.fixture()
def make_inbound():
    return _make_inbound


@pytest.fixture()
def pdf_attachment():
    return _pdf_attachment


@pytest.fixture()
def docx_attachment():
    return _docx_attachment


@pytest.fixture()
def enqueue_ingest(db: Session):
    """Helper to kick off the pipeline the way the poller would."""
    from app.jobs import queue as q
    def _enqueue(message_id: str) -> None:
        q.enqueue(db, type="ingest_email", payload={"message_id": message_id})
        db.commit()
    return _enqueue
