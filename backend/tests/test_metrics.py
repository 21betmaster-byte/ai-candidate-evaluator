"""Tests for GET /api/metrics — technical and business metrics aggregation."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from app.models import Candidate, Evaluation, Job, ProcessingLog


def _utc(minutes_offset: int = 0) -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=minutes_offset)


def _make_candidate(db: Session, email: str, status: str = "pending", **kw) -> Candidate:
    c = Candidate(email=email, status=status, **kw)
    db.add(c)
    db.flush()
    return c


def _make_log(
    db: Session,
    candidate_id: int,
    step: str,
    message: str = "started",
    level: str = "info",
    meta: dict | None = None,
    created_at: datetime | None = None,
) -> ProcessingLog:
    row = ProcessingLog(
        candidate_id=candidate_id,
        step=step,
        message=message,
        level=level,
        meta=meta or {},
    )
    db.add(row)
    db.flush()
    if created_at is not None:
        # Bypass server_default by updating after flush
        row.created_at = created_at
        db.add(row)
        db.flush()
    return row


def _make_job(db: Session, candidate_id: int, job_type: str, status: str, attempts: int) -> Job:
    j = Job(
        candidate_id=candidate_id,
        type=job_type,
        status=status,
        attempts=attempts,
        max_attempts=5,
    )
    db.add(j)
    db.flush()
    return j


# ── empty DB ─────────────────────────────────────────────────────────


def test_empty_db(client, settings_row):
    r = client.get("/api/metrics")
    assert r.status_code == 200
    d = r.json()

    tech = d["technical"]
    assert tech["first_response_latency_seconds"] is None
    assert tech["evaluation_latency_seconds"] is None
    assert tech["decision_email_latency_seconds"] is None
    assert tech["processing_error_rate"] is None
    assert tech["retry_success_rate"] is None
    assert tech["override_rate"] is None

    biz = d["business"]
    assert biz["funnel"] == []
    assert biz["avg_time_to_decision_seconds"] is None
    assert biz["pass_rate"] is None
    assert biz["avg_score"] is None
    assert biz["candidates_per_day"] == []
    assert biz["total_llm_input_tokens"] == 0
    assert biz["total_llm_output_tokens"] == 0


# ── not-tracked fields ───────────────────────────────────────────────


def test_not_tracked_fields(client, settings_row):
    r = client.get("/api/metrics")
    tech = r.json()["technical"]
    for field in [
        "edge_case_classification_accuracy",
        "duplicate_detection_accuracy",
        "email_bounce_rate",
        "agent_uptime",
        "dashboard_load_time",
    ]:
        assert tech[field]["value"] is None
        assert isinstance(tech[field]["reason"], str)
        assert len(tech[field]["reason"]) > 0


# ── funnel ───────────────────────────────────────────────────────────


def test_funnel_counts(client, db, settings_row):
    _make_candidate(db, "a@x.com", "auto_pass")
    _make_candidate(db, "b@x.com", "auto_pass")
    _make_candidate(db, "c@x.com", "auto_fail")
    _make_candidate(db, "d@x.com", "pending")
    db.commit()

    r = client.get("/api/metrics")
    funnel = {e["status"]: e["count"] for e in r.json()["business"]["funnel"]}
    assert funnel["auto_pass"] == 2
    assert funnel["auto_fail"] == 1
    assert funnel["pending"] == 1


# ── processing error rate ────────────────────────────────────────────


def test_processing_error_rate(client, db, settings_row):
    for i in range(8):
        _make_candidate(db, f"ok{i}@x.com", "auto_pass")
    _make_candidate(db, "err1@x.com", "processing_error")
    _make_candidate(db, "err2@x.com", "processing_error")
    db.commit()

    r = client.get("/api/metrics")
    assert r.json()["technical"]["processing_error_rate"] == 0.2


# ── pass rate ────────────────────────────────────────────────────────


def test_pass_rate(client, db, settings_row):
    for i in range(3):
        _make_candidate(db, f"pass{i}@x.com", "auto_pass")
    _make_candidate(db, "fail@x.com", "auto_fail")
    db.commit()

    r = client.get("/api/metrics")
    assert r.json()["business"]["pass_rate"] == 0.75


# ── override rate ────────────────────────────────────────────────────


def test_override_rate(client, db, settings_row):
    _make_candidate(db, "a@x.com", "auto_pass")
    _make_candidate(db, "b@x.com", "auto_fail")
    _make_candidate(db, "c@x.com", "passed_manual")
    _make_candidate(db, "d@x.com", "failed_manual")
    db.commit()

    r = client.get("/api/metrics")
    # 2 manual out of 4 decided = 0.5
    assert r.json()["technical"]["override_rate"] == 0.5


# ── retry success rate ───────────────────────────────────────────────


def test_retry_success_rate(client, db, settings_row):
    c = _make_candidate(db, "a@x.com")
    _make_job(db, c.id, "fetch_github", "done", attempts=3)
    _make_job(db, c.id, "fetch_portfolio", "done", attempts=2)
    _make_job(db, c.id, "score", "failed", attempts=5)
    # This job had only 1 attempt — should NOT count
    _make_job(db, c.id, "classify", "done", attempts=1)
    db.commit()

    r = client.get("/api/metrics")
    # 2 retried-and-done out of 3 retried total
    rate = r.json()["technical"]["retry_success_rate"]
    assert abs(rate - 0.6667) < 0.001


# ── avg score ────────────────────────────────────────────────────────


def test_avg_score(client, db, settings_row):
    c1 = _make_candidate(db, "a@x.com", "auto_pass")
    c2 = _make_candidate(db, "b@x.com", "auto_fail")
    ev1 = Evaluation(candidate_id=c1.id, overall_score=80.0)
    ev2 = Evaluation(candidate_id=c2.id, overall_score=40.0)
    db.add_all([ev1, ev2])
    db.commit()

    r = client.get("/api/metrics")
    assert r.json()["business"]["avg_score"] == 60.0


# ── first response latency ──────────────────────────────────────────


def test_first_response_latency(client, db, settings_row):
    t0 = _utc(-10)
    t1 = t0 + timedelta(seconds=20)
    c = _make_candidate(db, "a@x.com")
    _make_log(db, c.id, "ingest", "started", created_at=t0)
    _make_log(db, c.id, "send_email", "sent missing_items", created_at=t1)
    db.commit()

    r = client.get("/api/metrics")
    assert r.json()["technical"]["first_response_latency_seconds"] == 20.0


# ── evaluation latency ───────────────────────────────────────────────


def test_evaluation_latency(client, db, settings_row):
    t0 = _utc(-10)
    t1 = t0 + timedelta(seconds=120)
    c = _make_candidate(db, "a@x.com")
    _make_log(db, c.id, "ingest", "started", created_at=t0)
    _make_log(db, c.id, "score", "completed", created_at=t1)
    db.commit()

    r = client.get("/api/metrics")
    assert r.json()["technical"]["evaluation_latency_seconds"] == 120.0


# ── decision email latency ───────────────────────────────────────────


def test_decision_email_latency(client, db, settings_row):
    t0 = _utc(-10)
    t1 = t0 + timedelta(seconds=5)
    c = _make_candidate(db, "a@x.com")
    _make_log(db, c.id, "decide", "tier=auto_pass score=80", created_at=t0)
    _make_log(db, c.id, "send_email", "sent pass_decision", created_at=t1)
    db.commit()

    r = client.get("/api/metrics")
    assert r.json()["technical"]["decision_email_latency_seconds"] == 5.0


# ── LLM token usage ─────────────────────────────────────────────────


def test_llm_token_usage(client, db, settings_row):
    c = _make_candidate(db, "a@x.com")
    _make_log(db, c.id, "structure_profile.detail", "profile structured", meta={
        "llm_input_tokens": 1000, "llm_output_tokens": 200,
    })
    _make_log(db, c.id, "score.detail", "scored 75", meta={
        "llm_input_tokens": 2000, "llm_output_tokens": 500,
    })
    db.commit()

    r = client.get("/api/metrics")
    biz = r.json()["business"]
    assert biz["total_llm_input_tokens"] == 3000
    assert biz["total_llm_output_tokens"] == 700


# ── candidates per day ───────────────────────────────────────────────


def test_candidates_per_day(client, db, settings_row):
    now = datetime.now(timezone.utc)
    today = now.replace(hour=12, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)

    c1 = _make_candidate(db, "a@x.com", "auto_pass")
    c2 = _make_candidate(db, "b@x.com", "auto_fail")
    c3 = _make_candidate(db, "c@x.com", "auto_pass")
    c1.updated_at = today
    c2.updated_at = today
    c3.updated_at = yesterday
    db.add_all([c1, c2, c3])
    db.commit()

    r = client.get("/api/metrics")
    daily = r.json()["business"]["candidates_per_day"]
    by_date = {e["date"]: e["count"] for e in daily}
    assert by_date[str(yesterday.date())] == 1
    assert by_date[str(today.date())] == 2


# ── avg time to decision ────────────────────────────────────────────


def test_avg_time_to_decision(client, db, settings_row):
    now = datetime.now(timezone.utc)
    c1 = _make_candidate(db, "a@x.com", "auto_pass")
    c2 = _make_candidate(db, "b@x.com", "auto_fail")
    c1.created_at = now - timedelta(seconds=100)
    c1.updated_at = now
    c2.created_at = now - timedelta(seconds=200)
    c2.updated_at = now
    db.add_all([c1, c2])
    db.commit()

    r = client.get("/api/metrics")
    avg_ttd = r.json()["business"]["avg_time_to_decision_seconds"]
    assert avg_ttd == 150.0


# ── error handling (fix 1) ──────────────────────────────────────────


def test_db_failure_returns_502(client, settings_row):
    with patch(
        "app.routes.metrics._compute_technical",
        side_effect=RuntimeError("simulated DB failure"),
    ):
        r = client.get("/api/metrics")
    assert r.status_code == 502
    assert "metrics aggregation failed" in r.json()["detail"]


# ── zero-rate vs no-data (fix 4) ────────────────────────────────────


def test_zero_error_rate_is_not_none(client, db, settings_row):
    """When all candidates succeed, error_rate should be 0.0, not None."""
    for i in range(5):
        _make_candidate(db, f"ok{i}@x.com", "auto_pass")
    db.commit()

    r = client.get("/api/metrics")
    assert r.json()["technical"]["processing_error_rate"] == 0.0


# ── missing token keys warn (fix 2) ─────────────────────────────────


def test_missing_token_keys_logs_warning(client, db, settings_row, caplog):
    c = _make_candidate(db, "a@x.com")
    _make_log(db, c.id, "structure_profile.detail", "profile structured", meta={})
    db.commit()

    with caplog.at_level(logging.WARNING, logger="app.routes.metrics"):
        r = client.get("/api/metrics")
    assert r.status_code == 200
    assert any("missing token keys" in rec.message for rec in caplog.records)
