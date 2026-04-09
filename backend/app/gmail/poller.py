"""Inbox poller. Lists unprocessed messages, dedupes against email_logs, and
enqueues an `ingest_email` job for each new one. Marks the gmail message with the
`processed` label so we never re-pick it up."""
from __future__ import annotations

import structlog

from app.db import session_scope
from app.gmail import client as gmail
from app.jobs import queue
from app.models import EmailLog

log = structlog.get_logger()


def poll_inbox() -> int:
    """Returns the number of newly enqueued messages."""
    new_count = 0
    try:
        ids = gmail.list_unprocessed_messages()
    except Exception as e:
        log.exception("poller.list_failed", error=str(e))
        raise
    for mid in ids:
        with session_scope() as db:
            existing = db.query(EmailLog).filter(EmailLog.gmail_message_id == mid, EmailLog.direction == "in").first()
            if existing:
                # Already known. Mark processed in Gmail to clean up the inbox view.
                try:
                    gmail.mark_processed(mid)
                except Exception:
                    pass
                continue
            queue.enqueue(db, type="ingest_email", payload={"message_id": mid})
        new_count += 1
    return new_count
