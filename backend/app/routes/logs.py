from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func as sa_func
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
    email: str | None = Query(default=None, max_length=254),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: str = Depends(require_user),
):
    # Subquery: most-recent log timestamp per candidate (used to sort groups)
    max_ts_sub = (
        db.query(
            ProcessingLog.candidate_id,
            sa_func.max(ProcessingLog.created_at).label("max_ts"),
        )
        .group_by(ProcessingLog.candidate_id)
        .subquery()
    )

    q = (
        db.query(ProcessingLog, Candidate.name, Candidate.email)
        .outerjoin(Candidate, ProcessingLog.candidate_id == Candidate.id)
        .outerjoin(max_ts_sub, ProcessingLog.candidate_id == max_ts_sub.c.candidate_id)
    )
    if step:
        q = q.filter(ProcessingLog.step == step)
    if level:
        q = q.filter(ProcessingLog.level == level)
    if candidate_id is not None:
        q = q.filter(ProcessingLog.candidate_id == candidate_id)
    if email:
        safe = email.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        q = q.filter(Candidate.email.ilike(f"%{safe}%", escape="\\"))

    # Group by candidate: newest-active candidate first, chronological within group.
    # System logs (candidate_id IS NULL) sort to the end.
    rows = (
        q.order_by(
            max_ts_sub.c.max_ts.desc().nullslast(),
            ProcessingLog.candidate_id,
            ProcessingLog.created_at.asc(),
        )
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
