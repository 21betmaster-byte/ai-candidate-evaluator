"""Postgres-backed job queue.

Workers claim due jobs with SELECT ... FOR UPDATE SKIP LOCKED. Failed jobs are
rescheduled with exponential backoff. After max_attempts, the candidate is moved
to processing_error and the job is marked failed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.logging_setup import log_event
from app.models import Job

# PRD §6: 1m → 5m → 15m → 1h → flag
BACKOFF_SCHEDULE_SECONDS = [60, 300, 900, 3600]


def enqueue(
    db: Session,
    type: str,
    payload: dict[str, Any] | None = None,
    candidate_id: int | None = None,
    delay_seconds: int = 0,
    max_attempts: int = 5,
) -> Job:
    job = Job(
        type=type,
        payload=payload or {},
        candidate_id=candidate_id,
        next_run_at=datetime.now(timezone.utc) + timedelta(seconds=delay_seconds),
        max_attempts=max_attempts,
    )
    db.add(job)
    db.flush()
    return job


def claim_due(db: Session, limit: int = 5) -> list[Job]:
    """Claim up to `limit` due jobs atomically. Marks them running."""
    sql = text(
        """
        WITH due AS (
            SELECT id FROM jobs
            WHERE status = 'pending' AND next_run_at <= now()
            ORDER BY next_run_at
            FOR UPDATE SKIP LOCKED
            LIMIT :limit
        )
        UPDATE jobs
        SET status = 'running', updated_at = now()
        WHERE id IN (SELECT id FROM due)
        RETURNING id
        """
    )
    ids = [row[0] for row in db.execute(sql, {"limit": limit}).all()]
    db.commit()
    if not ids:
        return []
    return db.query(Job).filter(Job.id.in_(ids)).all()


def complete(db: Session, job: Job) -> None:
    job.status = "done"
    job.last_error = None
    db.add(job)
    db.commit()


def fail_with_backoff(db: Session, job: Job, error: str) -> bool:
    """Reschedule with backoff. Returns True if exhausted (caller should escalate).

    Emits a ProcessingLog row on every retry so the candidate's timeline on
    the dashboard shows each infra failure + the scheduled retry delay
    (PRD §3: "Infrastructure failures are logged with: which service, error
    type, retry count, resolution")."""
    job.attempts += 1
    job.last_error = error[:4000]
    if job.attempts >= job.max_attempts:
        job.status = "failed"
        db.add(job)
        db.commit()
        log_event(
            db, job.candidate_id, job.type,
            f"retries exhausted ({job.attempts}/{job.max_attempts})",
            level="error",
            meta={"job_id": job.id, "attempts": job.attempts, "error": error[:500]},
        )
        db.commit()
        return True
    delay = BACKOFF_SCHEDULE_SECONDS[min(job.attempts - 1, len(BACKOFF_SCHEDULE_SECONDS) - 1)]
    job.status = "pending"
    job.next_run_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
    db.add(job)
    db.commit()
    log_event(
        db, job.candidate_id, job.type,
        f"retry scheduled in {delay}s (attempt {job.attempts}/{job.max_attempts})",
        level="warn",
        meta={"job_id": job.id, "attempts": job.attempts, "delay_seconds": delay, "error": error[:500]},
    )
    db.commit()
    return False
