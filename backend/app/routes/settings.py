from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import require_user
from app.db import get_db
from app.models import AppSettings
from app.schemas import SettingsModel

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=SettingsModel)
def get_settings_route(db: Session = Depends(get_db), user: str = Depends(require_user)):
    row = db.get(AppSettings, 1)
    if not row:
        raise HTTPException(500, "settings row missing")
    return SettingsModel.model_validate(row)


@router.put("", response_model=SettingsModel)
def update_settings_route(body: SettingsModel, db: Session = Depends(get_db), user: str = Depends(require_user)):
    # Pydantic already validated: rubric non-empty, unique keys, weights sum to 100.
    t = body.tier_thresholds
    if not (t.get("auto_fail_ceiling", 0) < t.get("manual_review_ceiling", 0) < t.get("auto_pass_floor", 0)):
        raise HTTPException(400, "thresholds must be ordered: auto_fail < manual_review < auto_pass")

    row = db.get(AppSettings, 1) or AppSettings(id=1)
    row.polling_minutes = body.polling_minutes
    row.rubric = [d.model_dump() for d in body.rubric]
    row.tier_thresholds = body.tier_thresholds
    row.pass_next_steps_text = body.pass_next_steps_text
    row.reminder_hours = body.reminder_hours
    row.company_name = body.company_name
    db.add(row)
    db.commit()
    db.refresh(row)
    return SettingsModel.model_validate(row)
