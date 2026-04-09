"""Move a candidate to processing_error after retries are exhausted.

Safety net: also emails the candidate a generic "we hit a snag, please resend"
notice so they never disappear silently after the initial acknowledgment.
The email is enqueued (not sent inline) so this function stays cheap and
never raises from inside the worker loop.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.jobs import queue
from app.models import Candidate, Job, ProcessingLog


def escalate_processing_error(db: Session, job: Job) -> None:
    if not job.candidate_id:
        return
    cand = db.get(Candidate, job.candidate_id)
    if not cand:
        return
    cand.status = "processing_error"
    db.add(cand)
    db.add(ProcessingLog(
        candidate_id=cand.id,
        step=job.type,
        level="error",
        message=f"Job {job.type} exhausted retries: {job.last_error}",
        meta={"job_id": job.id, "attempts": job.attempts},
    ))
    # Safety-net notice to the candidate so they aren't left hanging after
    # the initial acknowledgment.
    if cand.email:
        queue.enqueue(
            db,
            type="send_template_email",
            candidate_id=cand.id,
            payload={
                "template": "processing_error_notice",
                "to": cand.email,
                "name": cand.name,
            },
        )
    db.commit()
