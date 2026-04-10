"""Aggregated technical and business metrics.

Derives latencies, error rates, funnel counts, and LLM token usage from the
existing ProcessingLog, Job, Candidate, and Evaluation tables. All date
arithmetic is done in Python so the queries work identically on Postgres
(production) and SQLite (tests).
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.auth import require_user
from app.db import get_db
from app.models import Candidate, Evaluation, Job, ProcessingLog
from app.schemas import (
    BusinessMetrics,
    DailyCount,
    FunnelEntry,
    MetricsResponse,
    NotTrackedMetric,
    TechnicalMetrics,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/metrics", tags=["metrics"])

TERMINAL_STATUSES = (
    "auto_pass", "auto_fail", "passed_manual", "failed_manual", "processing_error",
)
DECIDED_STATUSES = (
    "auto_pass", "auto_fail", "passed_manual", "failed_manual",
)
MANUAL_STATUSES = ("passed_manual", "failed_manual")

_NOT_TRACKED = {
    "edge_case_classification_accuracy": "Requires labeled ground-truth data",
    "duplicate_detection_accuracy": "Duplicate detection not implemented",
    "email_bounce_rate": "Gmail API bounce status not captured",
    "agent_uptime": "No persistent uptime tracking",
    "dashboard_load_time": "Requires frontend instrumentation",
}


@router.get("", response_model=MetricsResponse)
def get_metrics(
    db: Session = Depends(get_db),
    user: str = Depends(require_user),
) -> MetricsResponse:
    try:
        return MetricsResponse(
            technical=_compute_technical(db),
            business=_compute_business(db),
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("metrics aggregation failed")
        raise HTTPException(502, "metrics aggregation failed — check server logs")


# ── helpers ──────────────────────────────────────────────────────────


def _avg_seconds(pairs: list[tuple[datetime, datetime]]) -> float | None:
    diffs = [(b - a).total_seconds() for a, b in pairs if a is not None and b is not None]
    return round(sum(diffs) / len(diffs), 2) if diffs else None


def _latency(db: Session, start_step: str, start_msg: str, end_step: str, end_msg_like: str) -> float | None:
    """Average seconds between two ProcessingLog events per candidate."""
    start_sub = (
        db.query(
            ProcessingLog.candidate_id,
            func.min(ProcessingLog.created_at).label("t"),
        )
        .filter(ProcessingLog.step == start_step, ProcessingLog.message == start_msg)
        .group_by(ProcessingLog.candidate_id)
        .subquery()
    )
    end_sub = (
        db.query(
            ProcessingLog.candidate_id,
            func.min(ProcessingLog.created_at).label("t"),
        )
        .filter(ProcessingLog.step == end_step, ProcessingLog.message.like(end_msg_like))
        .group_by(ProcessingLog.candidate_id)
        .subquery()
    )
    pairs = (
        db.query(start_sub.c.t, end_sub.c.t)
        .join(end_sub, start_sub.c.candidate_id == end_sub.c.candidate_id)
        .all()
    )
    return _avg_seconds(pairs)


def _decision_email_latency(db: Session) -> float | None:
    """Avg seconds from decide log to decision email send."""
    start_sub = (
        db.query(
            ProcessingLog.candidate_id,
            func.min(ProcessingLog.created_at).label("t"),
        )
        .filter(ProcessingLog.step == "decide")
        .group_by(ProcessingLog.candidate_id)
        .subquery()
    )
    end_sub = (
        db.query(
            ProcessingLog.candidate_id,
            func.min(ProcessingLog.created_at).label("t"),
        )
        .filter(
            ProcessingLog.step == "send_email",
            or_(
                ProcessingLog.message.like("sent pass_decision%"),
                ProcessingLog.message.like("sent fail_decision%"),
            ),
        )
        .group_by(ProcessingLog.candidate_id)
        .subquery()
    )
    pairs = (
        db.query(start_sub.c.t, end_sub.c.t)
        .join(end_sub, start_sub.c.candidate_id == end_sub.c.candidate_id)
        .all()
    )
    return _avg_seconds(pairs)


def _safe_ratio(numerator: int, denominator: int) -> float | None:
    """Return the ratio, or ``None`` only when *denominator* is 0 (no data).

    A numerator of 0 with a positive denominator is a genuine 0.0 rate,
    not "no data".
    """
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)


# ── technical ────────────────────────────────────────────────────────


def _compute_technical(db: Session) -> TechnicalMetrics:
    # Latencies
    ack_latency = _latency(db, "ingest", "started", "send_email", "sent acknowledgment%")
    eval_latency = _latency(db, "ingest", "started", "score", "completed")
    decision_latency = _decision_email_latency(db)

    # Processing error rate
    total = db.query(func.count(Candidate.id)).scalar() or 0
    errors = db.query(func.count(Candidate.id)).filter(Candidate.status == "processing_error").scalar() or 0
    error_rate = _safe_ratio(errors, total)

    # Retry success rate
    retried = db.query(func.count(Job.id)).filter(Job.attempts > 1).scalar() or 0
    retried_ok = db.query(func.count(Job.id)).filter(Job.attempts > 1, Job.status == "done").scalar() or 0
    retry_rate = _safe_ratio(retried_ok, retried)

    # Override rate
    decided = db.query(func.count(Candidate.id)).filter(Candidate.status.in_(DECIDED_STATUSES)).scalar() or 0
    manual = db.query(func.count(Candidate.id)).filter(Candidate.status.in_(MANUAL_STATUSES)).scalar() or 0
    override = _safe_ratio(manual, decided)

    return TechnicalMetrics(
        ack_latency_seconds=ack_latency,
        evaluation_latency_seconds=eval_latency,
        decision_email_latency_seconds=decision_latency,
        processing_error_rate=error_rate,
        retry_success_rate=retry_rate,
        override_rate=override,
        **{k: NotTrackedMetric(reason=v) for k, v in _NOT_TRACKED.items()},
    )


# ── business ─────────────────────────────────────────────────────────


def _compute_business(db: Session) -> BusinessMetrics:
    # Funnel
    funnel_rows = (
        db.query(Candidate.status, func.count(Candidate.id))
        .group_by(Candidate.status)
        .all()
    )
    funnel = [FunnelEntry(status=s, count=c) for s, c in funnel_rows]

    # Avg time to decision (terminal candidates only)
    terminal = (
        db.query(Candidate.created_at, Candidate.updated_at)
        .filter(Candidate.status.in_(TERMINAL_STATUSES))
        .all()
    )
    avg_ttd = _avg_seconds([(c, u) for c, u in terminal]) if terminal else None

    # Pass rate (automated decisions only)
    auto_pass = db.query(func.count(Candidate.id)).filter(Candidate.status == "auto_pass").scalar() or 0
    auto_fail = db.query(func.count(Candidate.id)).filter(Candidate.status == "auto_fail").scalar() or 0
    pass_rate = _safe_ratio(auto_pass, auto_pass + auto_fail)

    # Avg score
    avg_raw = db.query(func.avg(Evaluation.overall_score)).filter(
        Evaluation.overall_score.isnot(None),
    ).scalar()
    avg_score = round(float(avg_raw), 2) if avg_raw is not None else None

    # Candidates per day (last 30 days) — grouped in Python so the query
    # works identically on Postgres and SQLite (no func.date()).
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    terminal_rows = (
        db.query(Candidate.updated_at)
        .filter(Candidate.status.in_(TERMINAL_STATUSES), Candidate.updated_at >= cutoff)
        .all()
    )
    day_counts: Counter[str] = Counter(
        r.updated_at.date().isoformat() for r in terminal_rows if r.updated_at is not None
    )
    candidates_per_day = sorted(
        [DailyCount(date=d, count=c) for d, c in day_counts.items()],
        key=lambda e: e.date,
    )

    # LLM token usage (sum from detail log rows)
    token_rows = (
        db.query(ProcessingLog.id, ProcessingLog.step, ProcessingLog.meta)
        .filter(ProcessingLog.step.in_(["structure_profile.detail", "score.detail"]))
        .all()
    )
    total_in = 0
    total_out = 0
    for r in token_rows:
        meta = r.meta or {}
        missing = [k for k in ("llm_input_tokens", "llm_output_tokens") if k not in meta]
        if missing:
            logger.warning(
                "ProcessingLog %s (%s) missing token keys: %s",
                r.id, r.step, ", ".join(missing),
            )
        total_in += meta.get("llm_input_tokens", 0)
        total_out += meta.get("llm_output_tokens", 0)

    return BusinessMetrics(
        funnel=funnel,
        avg_time_to_decision_seconds=avg_ttd,
        pass_rate=pass_rate,
        avg_score=avg_score,
        candidates_per_day=candidates_per_day,
        total_llm_input_tokens=total_in,
        total_llm_output_tokens=total_out,
    )
