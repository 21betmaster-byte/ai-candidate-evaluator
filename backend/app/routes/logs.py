from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import require_user
from app.db import get_db
from app.models import Candidate, ProcessingLog
from app.schemas import LogEntryWithCandidate

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("", response_model=list[LogEntryWithCandidate])
def list_logs(
    step: str | None = Query(default=None),
    level: str | None = Query(default=None),
    candidate_id: int | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: str = Depends(require_user),
):
    q = (
        db.query(ProcessingLog, Candidate.name, Candidate.email)
        .outerjoin(Candidate, ProcessingLog.candidate_id == Candidate.id)
    )
    if step:
        q = q.filter(ProcessingLog.step == step)
    if level:
        q = q.filter(ProcessingLog.level == level)
    if candidate_id is not None:
        q = q.filter(ProcessingLog.candidate_id == candidate_id)

    rows = (
        q.order_by(ProcessingLog.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return [
        LogEntryWithCandidate(
            id=log.id,
            step=log.step,
            level=log.level,
            message=log.message,
            meta=log.meta,
            created_at=log.created_at,
            candidate_id=log.candidate_id,
            candidate_name=cand_name,
            candidate_email=cand_email,
        )
        for log, cand_name, cand_email in rows
    ]
