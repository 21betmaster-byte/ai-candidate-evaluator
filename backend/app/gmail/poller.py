"""Inbox poller. Lists unprocessed messages, dedupes against email_logs, and
enqueues an `ingest_email` job for each new one. Marks the gmail message with the
`processed` label so we never re-pick it up."""
from __future__ import annotations

from sqlalchemy import func

from app.db import session_scope
from app.gmail import client as gmail
from app.jobs import queue
from app.logging_setup import get_logger
from app.models import AppSettings, EmailLog

log = get_logger("poller")


def poll_inbox() -> int:
    """Returns the number of newly enqueued messages."""
    new_count = 0
    try:
        ids = gmail.list_unprocessed_messages()
    except Exception as e:
        log.exception("poller.list_failed", error=str(e))
        raise

    if not ids:
        log.info("poller.inbox_empty")
        return 0

    log.info("poller.gmail_listed", count=len(ids), message_ids=ids)

    for mid in ids:
        with session_scope() as db:
            existing = db.query(EmailLog).filter(EmailLog.gmail_message_id == mid, EmailLog.direction == "in").first()
            if existing:
                log.info("poller.skip_duplicate", message_id=mid, existing_log_id=existing.id)
                # Already known. Mark processed in Gmail to clean up the inbox view.
                try:
                    gmail.mark_processed(mid)
                except Exception:
                    pass
                continue
            queue.enqueue(db, type="ingest_email", payload={"message_id": mid})
            log.info("poller.enqueued", message_id=mid)
        new_count += 1

    # Persist the poll timestamp so the dashboard can display it.
    with session_scope() as db:
        row = db.get(AppSettings, 1)
        if row:
            row.last_polled_at = func.now()

    return new_count
