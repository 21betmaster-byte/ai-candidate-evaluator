"""Worker entrypoint. Polls the jobs table and dispatches handlers.

Run with: `python -m app.jobs.worker`
"""
from __future__ import annotations

import asyncio
import logging
import signal
import time

import structlog

from app.config import get_settings
from app.db import SessionLocal
from app.logging_setup import configure_logging, get_logger
from app.jobs import queue
from app.jobs.handlers import HANDLERS
from app.gmail.poller import poll_inbox
from app.models import AppSettings

log = get_logger("worker")
_stop = False


def _handle_signal(*_):
    global _stop
    _stop = True
    log.info("worker.shutdown_requested")


def run_one_job(job) -> None:
    handler = HANDLERS.get(job.type)
    db = SessionLocal()
    try:
        if handler is None:
            queue.fail_with_backoff(db, job, f"no handler for {job.type}")
            return
        try:
            handler(db, job)
            queue.complete(db, job)
            log.info("job.complete", job_id=job.id, type=job.type)
        except Exception as e:
            log.exception("job.failed", job_id=job.id, type=job.type, error=str(e))
            exhausted = queue.fail_with_backoff(db, job, repr(e))
            if exhausted:
                # Escalate: candidate processing_error
                from app.pipeline.escalate import escalate_processing_error
                escalate_processing_error(db, job)
    finally:
        db.close()


def maybe_poll_inbox(state: dict) -> None:
    """Run an inbox poll on the configured interval."""
    s = get_settings()
    db = SessionLocal()
    try:
        row = db.get(AppSettings, 1)
        interval_min = (row.polling_minutes if row else s.inbox_poll_interval_minutes) or 2
    finally:
        db.close()
    now = time.time()
    if now - state.get("last_poll_at", 0) >= interval_min * 60:
        state["last_poll_at"] = now
        try:
            count = poll_inbox()
            log.info("inbox.poll", new_messages=count)
        except Exception as e:
            log.exception("inbox.poll_failed", error=str(e))


def main():
    configure_logging()
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    s = get_settings()
    log.info("worker.start", poll_interval=s.worker_poll_interval_seconds)
    state: dict = {"last_poll_at": 0}
    while not _stop:
        # Periodic inbox poll
        maybe_poll_inbox(state)
        # Process jobs
        db = SessionLocal()
        try:
            jobs = queue.claim_due(db, limit=5)
        finally:
            db.close()
        if not jobs:
            time.sleep(s.worker_poll_interval_seconds)
            continue
        for j in jobs:
            run_one_job(j)


if __name__ == "__main__":
    main()
