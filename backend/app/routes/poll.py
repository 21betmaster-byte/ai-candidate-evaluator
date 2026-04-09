from fastapi import APIRouter, Depends

from app.auth import require_user
from app.gmail.poller import poll_inbox

router = APIRouter(prefix="/api/poll", tags=["poll"])


@router.post("")
def trigger_poll(user: str = Depends(require_user)):
    count = poll_inbox()
    return {"new_messages": count}
