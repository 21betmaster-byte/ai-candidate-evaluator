from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import cast, func as sa_func, or_, String
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
    # Subquery: most-recent log timestamp per group (candidate_id or NULL).
    # Coalesce NULL candidate_id to -1 so orphan logs form one sortable group.
    group_key = sa_func.coalesce(ProcessingLog.candidate_id, -1)
    max_ts_sub = (
        db.query(
            group_key.label("gk"),
            sa_func.max(ProcessingLog.created_at).label("max_ts"),
        )
        .group_by(group_key)
        .subquery()
    )

    q = (
        db.query(ProcessingLog, Candidate.name, Candidate.email)
        .outerjoin(Candidate, ProcessingLog.candidate_id == Candidate.id)
        .outerjoin(
            max_ts_sub,
            sa_func.coalesce(ProcessingLog.candidate_id, -1) == max_ts_sub.c.gk,
        )
    )
    if step:
        q = q.filter(ProcessingLog.step == step)
    if level:
        q = q.filter(ProcessingLog.level == level)
    if candidate_id is not None:
        q = q.filter(ProcessingLog.candidate_id == candidate_id)
    if email:
        safe = email.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        # Search both candidate email AND the sender field in log meta
        # so orphan logs (non-application emails) are findable too.
        q = q.filter(
            or_(
                Candidate.email.ilike(f"%{safe}%", escape="\\"),
                cast(ProcessingLog.meta["sender"].astext, String).ilike(f"%{safe}%", escape="\\"),
            )
        )

    # Group by candidate: newest-active group first, chronological within group.
    # Orphan logs (candidate_id IS NULL) sort by their own max_ts alongside candidates.
    rows = (
        q.order_by(
            max_ts_sub.c.max_ts.desc(),
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
            candidate_email=cand_email or (log.meta or {}).get("sender"),
        )
        for log, cand_name, cand_email in rows
    ]
