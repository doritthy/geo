"""Web Push subscription management for the current user."""

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import PushSubscription, User
from app.security import get_current_user

router = APIRouter(tags=["push"])


class PushKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscriptionIn(BaseModel):
    endpoint: str
    keys: PushKeys


@router.get("/api/push/config")
def push_config() -> dict:
    s = get_settings()
    return {"enabled": s.push_configured, "public_key": s.VAPID_PUBLIC_KEY or None}


@router.post("/api/push/subscriptions", status_code=status.HTTP_204_NO_CONTENT)
def subscribe(body: PushSubscriptionIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> None:
    sub = db.query(PushSubscription).filter(PushSubscription.endpoint == body.endpoint).first()
    if sub is None:
        sub = PushSubscription(endpoint=body.endpoint, user_id=user.id, p256dh=body.keys.p256dh, auth=body.keys.auth)
        db.add(sub)
    else:  # same browser, maybe another account now
        sub.user_id, sub.p256dh, sub.auth = user.id, body.keys.p256dh, body.keys.auth
    db.commit()


@router.delete("/api/push/subscriptions", status_code=status.HTTP_204_NO_CONTENT)
def unsubscribe(endpoint: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> None:
    db.query(PushSubscription).filter(PushSubscription.endpoint == endpoint, PushSubscription.user_id == user.id).delete()
    db.commit()
