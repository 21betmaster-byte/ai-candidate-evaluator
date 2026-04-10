from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, asc
from sqlalchemy.orm import Session, joinedload

from app.auth import require_user
from app.db import get_db
from app.gmail import client as gmail
from app.jobs import queue
from app.models import Candidate, EmailLog, Evaluation, ProcessingLog
from app.schemas import (
    CandidateRow,
    CandidateDetail,
    EmailHistoryEntry,
    EvaluationDetail,
    ProcessingLogEntry,
    ManualDecisionRequest,
)

router = APIRouter(prefix="/api/candidates", tags=["candidates"])


@router.get("", response_model=list[CandidateRow])
def list_candidates(
    status: str | None = Query(default=None),
    sort: str = Query(default="created_desc"),
    db: Session = Depends(get_db),
    user: str = Depends(require_user),
):
    q = db.query(
        Candidate.id,
        Candidate.email,
        Candidate.name,
        Candidate.status,
        Evaluation.overall_score,
        Candidate.created_at,
    ).outerjoin(Evaluation, Evaluation.id == Candidate.current_evaluation_id)

    if status:
        q = q.filter(Candidate.status == status)

    if sort == "score_desc":
        q = q.order_by(desc(Evaluation.overall_score).nullslast())
    elif sort == "score_asc":
        q = q.order_by(asc(Evaluation.overall_score).nullsfirst())
    elif sort == "created_asc":
        q = q.order_by(asc(Candidate.created_at))
    else:
        q = q.order_by(desc(Candidate.created_at))

    rows = q.limit(500).all()
    return [
        CandidateRow(
            id=r.id, email=r.email, name=r.name, status=r.status,
            overall_score=r.overall_score, created_at=r.created_at,
        )
        for r in rows
    ]


@router.get("/{candidate_id}", response_model=CandidateDetail)
def get_candidate(candidate_id: int, db: Session = Depends(get_db), user: str = Depends(require_user)):
    cand = db.get(Candidate, candidate_id)
    if not cand:
        raise HTTPException(404, "candidate not found")
    ev = None
    if cand.current_evaluation_id:
        ev = db.get(Evaluation, cand.current_evaluation_id)
    logs = (
        db.query(ProcessingLog)
        .filter(ProcessingLog.candidate_id == candidate_id)
        .order_by(ProcessingLog.created_at.asc())
        .all()
    )
    email_rows = (
        db.query(EmailLog)
        .filter(EmailLog.candidate_id == candidate_id)
        .order_by(EmailLog.created_at.asc())
        .all()
    )
    email_history = [_email_history_entry(row) for row in email_rows]
    return CandidateDetail(
        id=cand.id,
        email=cand.email,
        name=cand.name,
        status=cand.status,
        missing_items=cand.missing_items,
        review_source=cand.review_source,
        review_reason=cand.review_reason,
        created_at=cand.created_at,
        updated_at=cand.updated_at,
        current_evaluation=EvaluationDetail.model_validate(ev) if ev else None,
        logs=[ProcessingLogEntry.model_validate(l) for l in logs],
        email_history=email_history,
    )


def _email_history_entry(row: EmailLog) -> EmailHistoryEntry:
    """Build an EmailHistoryEntry, fetching the full body from Gmail when possible.

    Failure modes (each yields a populated `body_error` and `body=None` so the UI
    can render a placeholder without crashing):
      - row has no gmail_message_id (older outbound rows or rows that pre-date
        send-time logging)
      - Gmail API call raises (transient outage, expired token, deleted message)
    """
    body: str | None = None
    body_error: str | None = None
    if row.gmail_message_id:
        try:
            fetched = gmail.fetch_email(row.gmail_message_id)
            body = fetched.body_text or None
            if not body:
                body_error = "empty body"
        except Exception as e:  # noqa: BLE001 — degrade per-row, not per-page
            body_error = f"unavailable: {type(e).__name__}"
    else:
        body_error = "no gmail message id"
    if not body:
        # Fall back to the stored snippet so the UI always has something.
        body = row.body_snippet
    return EmailHistoryEntry(
        id=row.id,
        direction=row.direction,
        sender=row.sender,
        subject=row.subject,
        classification=row.classification,
        template_used=row.template_used,
        created_at=row.created_at,
        body=body,
        body_error=body_error,
    )


@router.post("/{candidate_id}/decision")
def manual_decision(
    candidate_id: int,
    body: ManualDecisionRequest,
    db: Session = Depends(get_db),
    user: str = Depends(require_user),
):
    cand = db.get(Candidate, candidate_id)
    if not cand:
        raise HTTPException(404, "candidate not found")
    if cand.status not in ("manual_review", "auto_pass", "auto_fail", "passed_manual", "failed_manual"):
        # Allow override even after auto-decision; PRD doesn't forbid it.
        pass

    settings_row = _settings(db)
    if body.decision == "pass":
        cand.status = "passed_manual"
        queue.enqueue(db, type="send_template_email", candidate_id=cand.id, payload={
            "template": "pass_decision",
            "to": cand.email,
            "name": cand.name,
            "next_steps": settings_row.pass_next_steps_text or "",
        })
    elif body.decision == "fail":
        cand.status = "failed_manual"
        ev = db.get(Evaluation, cand.current_evaluation_id) if cand.current_evaluation_id else None
        reason = (ev.decision_reason if ev else "") or ""
        queue.enqueue(db, type="send_template_email", candidate_id=cand.id, payload={
            "template": "fail_decision",
            "to": cand.email,
            "name": cand.name,
            "reason": reason,
        })
    else:
        raise HTTPException(400, "decision must be 'pass' or 'fail'")

    db.add(cand)
    db.commit()
    return {"ok": True, "status": cand.status}


@router.delete("/{candidate_id}")
def delete_candidate(
    candidate_id: int,
    db: Session = Depends(get_db),
    user: str = Depends(require_user),
):
    cand = db.get(Candidate, candidate_id)
    if not cand:
        raise HTTPException(404, "candidate not found")
    # Delete in dependency order
    db.query(ProcessingLog).filter(ProcessingLog.candidate_id == candidate_id).delete()
    db.query(EmailLog).filter(EmailLog.candidate_id == candidate_id).delete()
    from app.models import Job
    db.query(Job).filter(Job.candidate_id == candidate_id).delete()
    db.query(Evaluation).filter(Evaluation.candidate_id == candidate_id).delete()
    db.delete(cand)
    db.commit()
    return {"ok": True}


def _settings(db: Session):
    from app.models import AppSettings
    row = db.get(AppSettings, 1)
    if not row:
        row = AppSettings(id=1)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row
