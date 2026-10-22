"""Web Push notifications (VAPID). Without VAPID keys configured nothing is
sent. Like email, sending runs from background tasks and never fails the
request; subscriptions the push service reports as gone (404/410) are
deleted.

Generate keys:  python -m app.push
"""

from __future__ import annotations

import base64
import json
import logging
import uuid

from app.config import get_settings
from app.db import SessionLocal
from app.models import PushSubscription

logger = logging.getLogger(__name__)

# Replaced in tests to capture outgoing messages: (endpoint, payload dict).
outbox: list[tuple[str, dict]] | None = None


def _webpush(sub: PushSubscription, payload: dict) -> int | None:
    """Returns the HTTP status for a failed delivery, None on success."""
    from pywebpush import WebPushException, webpush

    s = get_settings()
    try:
        webpush(
            subscription_info={"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=s.VAPID_PRIVATE_KEY,
            vapid_claims={"sub": s.VAPID_SUBJECT},
            ttl=24 * 3600,
            timeout=10,
        )
        return None
    except WebPushException as exc:
        return exc.response.status_code if exc.response is not None else 0


def send_push(user_ids: list[uuid.UUID], title: str, body: str, url: str) -> None:
    ids = [u for u in set(user_ids) if u]
    if not ids or (outbox is None and not get_settings().push_configured):
        return
    payload = {"title": title, "body": body, "url": url}
    db = SessionLocal()
    try:
        subs = db.query(PushSubscription).filter(PushSubscription.user_id.in_(ids)).all()
        for sub in subs:
            if outbox is not None:
                outbox.append((sub.endpoint, payload))
                continue
            try:
                status = _webpush(sub, payload)
            except Exception:  # noqa: BLE001
                logger.exception("Push to %s failed", sub.endpoint[:60])
                continue
            if status in (404, 410):
                db.delete(sub)
            elif status is not None:
                logger.warning("Push to %s failed with HTTP %s", sub.endpoint[:60], status)
        db.commit()
    finally:
        db.close()


def generate_vapid_keys() -> tuple[str, str]:
    """(public, private) as base64url: uncompressed P-256 point / raw scalar."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    raw_priv = key.private_numbers().private_value.to_bytes(32, "big")
    raw_pub = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)

    def b64(b: bytes) -> str:
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

    return b64(raw_pub), b64(raw_priv)


if __name__ == "__main__":
    pub, priv = generate_vapid_keys()
    print(f"VAPID_PUBLIC_KEY={pub}\nVAPID_PRIVATE_KEY={priv}")
