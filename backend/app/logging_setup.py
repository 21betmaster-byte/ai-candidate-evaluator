"""End-to-end structured logging.

Two sinks, one API:

1. **stdlib/structlog sink** — JSON log lines to stdout (Railway collects these).
   Use for: debugging, latency investigation, infra failures.

2. **ProcessingLog DB sink** — one row per step per candidate, rendered on the
   dashboard's candidate detail page. Use for: hiring-manager audit trail and
   the "walk through the logs" exercise from the Plum Builders' Residency brief.

The `log_step` context manager writes to BOTH sinks and automatically captures
duration_ms and exceptions, so handlers don't have to remember. Per PRD §3
"Logging":

    - Every processing step is logged with timestamp
    - Edge case triggers are logged
    - Infrastructure failures are logged with error type + retry count
    - All logs are queryable (stdout JSON + DB rows)
    - Each candidate's processing timeline is viewable on detail page
"""
from __future__ import annotations

import logging
import sys
import time
from contextlib import contextmanager
from typing import Any, Iterator

import structlog
from sqlalchemy.orm import Session

from app.models import ProcessingLog

_configured = False


def configure_logging(json: bool = True, level: int = logging.INFO) -> None:
    """Idempotent logging setup. Call once at process startup."""
    global _configured
    if _configured:
        return
    _configured = True

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
        force=True,
    )

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    if json:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> Any:
    """Lazy accessor — configures on first use if not already done."""
    if not _configured:
        configure_logging()
    return structlog.get_logger(name)


def _write_log_row(
    db: Session,
    candidate_id: int | None,
    step: str,
    message: str,
    level: str,
    meta: dict | None,
) -> None:
    """Insert a ProcessingLog row. Never raises — logging must not break the
    pipeline it is observing."""
    try:
        db.add(
            ProcessingLog(
                candidate_id=candidate_id,
                step=step,
                level=level,
                message=message,
                meta=meta or {},
            )
        )
        db.flush()
    except Exception:  # pragma: no cover
        get_logger("logging_setup").exception(
            "processing_log_write_failed", step=step, candidate_id=candidate_id
        )


def log_event(
    db: Session | None,
    candidate_id: int | None,
    step: str,
    message: str,
    *,
    level: str = "info",
    meta: dict | None = None,
) -> None:
    """One-shot log: write both the stdout line and (if db given) a DB row.

    Use for discrete events that don't wrap a block of code (e.g. "github
    discovered from portfolio", "candidate rejected — linkedin only")."""
    logger = get_logger("pipeline")
    payload = {
        "candidate_id": candidate_id,
        "step": step,
        **(meta or {}),
    }
    log_fn = getattr(logger, level, logger.info)
    log_fn(message, **payload)
    if db is not None:
        _write_log_row(db, candidate_id, step, message, level, meta)


@contextmanager
def log_step(
    db: Session,
    candidate_id: int | None,
    step: str,
    *,
    meta: dict | None = None,
) -> Iterator[dict]:
    """Wrap a pipeline step. Emits start + completed/failed log lines with
    `duration_ms`. Yields a mutable dict so the caller can attach extra meta
    that will be included in the completion log.

    Usage::

        with log_step(db, cand.id, "fetch_github") as ctx:
            data = fetch_github(url)
            ctx["public_repos"] = data.public_repos
    """
    logger = get_logger("pipeline")
    extra: dict = dict(meta or {})
    base = {"candidate_id": candidate_id, "step": step, **extra}
    logger.info("step.started", **base)
    _write_log_row(db, candidate_id, step, "started", "info", extra)

    t0 = time.monotonic()
    ctx: dict = dict(extra)
    try:
        yield ctx
    except Exception as e:
        duration_ms = int((time.monotonic() - t0) * 1000)
        err_meta = {
            **ctx,
            "duration_ms": duration_ms,
            "error_type": type(e).__name__,
            "error": str(e)[:500],
        }
        logger.exception("step.failed", **{"candidate_id": candidate_id, "step": step, **err_meta})
        _write_log_row(
            db, candidate_id, step, f"failed: {type(e).__name__}: {e}"[:500], "error", err_meta
        )
        raise
    else:
        duration_ms = int((time.monotonic() - t0) * 1000)
        done_meta = {**ctx, "duration_ms": duration_ms}
        logger.info("step.completed", **{"candidate_id": candidate_id, "step": step, **done_meta})
        _write_log_row(db, candidate_id, step, "completed", "info", done_meta)
