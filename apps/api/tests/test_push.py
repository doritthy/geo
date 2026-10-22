"""Web Push: subscription management, delivery on issue events, cleanup of
subscriptions the push service reports as gone."""

from tests.test_issues import _admin, _worker

SUB = {"endpoint": "https://push.example.com/send/abc", "keys": {"p256dh": "BPk", "auth": "au"}}


def test_push_on_issue_assignment(client, monkeypatch):
    from app import push

    box: list = []
    monkeypatch.setattr(push, "outbox", box)
    h = _admin(client)
    pid = client.post("/api/projects", json={"name": "ЖК"}, headers=h).json()["id"]
    worker_id, wh = _worker(client, h, pid)
    assert client.get("/api/push/config", headers=h).json() == {"enabled": False, "public_key": None}
    assert client.post("/api/push/subscriptions", headers=wh, json=SUB).status_code == 204
    assert client.post("/api/push/subscriptions", headers=wh, json=SUB).status_code == 204  # idempotent

    r = client.post(f"/api/projects/{pid}/issues", headers=h, json={"title": "Оголение арматуры", "assignee_id": worker_id})
    assert r.status_code == 201
    assert len(box) == 1
    endpoint, payload = box[0]
    assert endpoint == SUB["endpoint"]
    assert "№1" in payload["title"] and "Оголение арматуры" in payload["body"]
    assert payload["url"] == f"/twin/{pid}?issue={r.json()['id']}"

    # The actor is never notified; unsubscribing stops delivery.
    client.patch(f"/api/issues/{r.json()['id']}", headers=wh, json={"status": "in_progress"})
    assert len(box) == 1
    client.delete("/api/push/subscriptions", headers=wh, params={"endpoint": SUB["endpoint"]})
    client.patch(f"/api/issues/{r.json()['id']}", headers=h, json={"title": "Оголение арматуры, ось 3"})
    assert len(box) == 1


def test_push_delivery_and_gone_subscription(client, monkeypatch):
    from app import push
    from app.config import get_settings
    from app.db import SessionLocal
    from app.models import PushSubscription, User

    pub, priv = push.generate_vapid_keys()
    assert len(pub) == 87 and len(priv) == 43
    s = get_settings()
    monkeypatch.setattr(s, "VAPID_PUBLIC_KEY", pub)
    monkeypatch.setattr(s, "VAPID_PRIVATE_KEY", priv)
    h = _admin(client)
    client.post("/api/push/subscriptions", headers=h, json=SUB)
    client.post("/api/push/subscriptions", headers=h, json={**SUB, "endpoint": "https://push.example.com/send/gone"})
    assert client.get("/api/push/config", headers=h).json()["public_key"] == pub

    sent = []

    def fake(sub, payload):
        sent.append(sub.endpoint)
        return 410 if sub.endpoint.endswith("gone") else None

    monkeypatch.setattr(push, "_webpush", fake)
    db = SessionLocal()
    uid = db.query(User).filter(User.email == "boss@example.com").one().id
    db.close()
    push.send_push([uid], "t", "b", "/")
    assert sorted(sent) == sorted([SUB["endpoint"], "https://push.example.com/send/gone"])
    db = SessionLocal()
    assert [p.endpoint for p in db.query(PushSubscription).all()] == [SUB["endpoint"]]
    db.close()


def test_webpush_encrypts_with_generated_keys(monkeypatch):
    """Real pywebpush encryption + VAPID signing with our key format; only HTTP is faked."""
    import base64
    import os

    import pywebpush
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    from app import push
    from app.config import get_settings
    from app.models import PushSubscription

    pub, priv = push.generate_vapid_keys()
    s = get_settings()
    monkeypatch.setattr(s, "VAPID_PUBLIC_KEY", pub)
    monkeypatch.setattr(s, "VAPID_PRIVATE_KEY", priv)
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()  # noqa: E731
    browser = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    sub = PushSubscription(endpoint="https://fcm.googleapis.com/fcm/send/x", p256dh=b64(browser), auth=b64(os.urandom(16)))

    calls = []

    class Resp:
        def __init__(self, code):
            self.status_code, self.text, self.headers, self.reason = code, "", {}, "Gone"

    def fake_post(url, data=None, headers=None, timeout=None, **kw):
        calls.append((url, headers, len(data)))
        return Resp(201 if len(calls) == 1 else 410)

    monkeypatch.setattr(pywebpush.requests, "post", fake_post)
    assert push._webpush(sub, {"title": "Предписание", "body": "x", "url": "/"}) is None
    url, headers, size = calls[0]
    assert url == sub.endpoint and headers["authorization"].startswith("vapid t=") and size > 0
    assert push._webpush(sub, {"title": "t", "body": "b", "url": "/"}) == 410
