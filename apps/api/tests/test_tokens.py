"""Open API personal tokens: owner's rights, read-only scope, revocation,
expiry, no token management with tokens."""

from datetime import datetime, timedelta, timezone

from tests.test_issues import _admin


def test_api_tokens(client):
    h = _admin(client)
    pid = client.post("/api/projects", json={"name": "ЖК"}, headers=h).json()["id"]
    ro = client.post("/api/tokens", headers=h, json={"name": "Power BI"}).json()
    rw = client.post("/api/tokens", headers=h, json={"name": "Шлюз 1С", "read_only": False, "expires_days": 30}).json()
    assert ro["token"].startswith("twk_") and ro["prefix"] == ro["token"][:12] and ro["read_only"] is True
    assert rw["expires_at"] is not None
    listed = client.get("/api/tokens", headers=h).json()
    assert {t["name"] for t in listed} == {"Power BI", "Шлюз 1С"} and "token" not in listed[0]

    rh = {"Authorization": f"Bearer {ro['token']}"}
    wh = {"Authorization": f"Bearer {rw['token']}"}
    assert client.get("/api/portfolio", headers=rh).status_code == 200
    assert client.get(f"/api/projects/{pid}/dashboard", headers=rh).json()["project"]["name"] == "ЖК"
    assert client.post(f"/api/projects/{pid}/issues", headers=rh, json={"title": "x"}).status_code == 403
    assert client.post(f"/api/projects/{pid}/issues", headers=wh, json={"title": "Из API"}).status_code == 201
    # Tokens cannot mint tokens.
    assert client.post("/api/tokens", headers=wh, json={"name": "evil", "read_only": False}).status_code == 403
    assert client.get("/api/tokens", headers=rh).status_code == 403
    assert client.get("/api/tokens", headers=h).json()[0]["last_used_at"] is not None

    # Revoke / expire.
    client.delete(f"/api/tokens/{ro['id']}", headers=h)
    assert client.get("/api/portfolio", headers=rh).status_code == 401
    from app.db import SessionLocal
    from app.models import ApiToken

    db = SessionLocal()
    t = db.get(ApiToken, __import__("uuid").UUID(rw["id"]))
    t.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    db.close()
    assert client.get("/api/portfolio", headers=wh).status_code == 401
    assert client.get("/api/portfolio", headers={"Authorization": "Bearer twk_nope"}).status_code == 401
