"""White-label branding: admins set name/colour/logo, everyone in the org reads it."""

import io

from tests.test_issues import _admin, _worker


def test_branding(client):
    from PIL import Image

    h = _admin(client)
    pid = client.post("/api/projects", json={"name": "ЖК"}, headers=h).json()["id"]
    _, wh = _worker(client, h, pid)
    assert client.get("/api/branding", headers=wh).json() == {"name": None, "color": None, "organization": "BI", "logo_url": None}
    assert client.put("/api/organization/branding", headers=wh, json={"name": "X"}).status_code == 403
    assert client.put("/api/organization/branding", headers=h, json={"color": "red"}).status_code == 400
    b = client.put("/api/organization/branding", headers=h, json={"name": "BI Twin", "color": "#e30613"}).json()
    assert b["name"] == "BI Twin" and b["color"] == "#E30613"

    buf = io.BytesIO()
    Image.new("RGB", (64, 32), (227, 6, 19)).save(buf, "PNG")
    r = client.post("/api/organization/branding/logo", headers=h, files={"file": ("logo.png", buf.getvalue(), "image/png")})
    assert r.status_code == 200 and r.json()["logo_url"].startswith("/api/branding/logo")
    got = client.get("/api/branding", headers=wh).json()
    logo = client.get(got["logo_url"], headers=wh)
    assert logo.status_code == 200 and logo.headers["content-type"] == "image/png" and logo.content[:4] == b"\x89PNG"
    bad = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    assert client.post("/api/organization/branding/logo", headers=h, files={"file": ("x.svg", bad, "image/svg+xml")}).status_code == 400
    assert client.post("/api/organization/branding/logo", headers=h, files={"file": ("x.txt", b"hi", "text/plain")}).status_code == 400
    assert client.delete("/api/organization/branding/logo", headers=h).json()["logo_url"] is None
    # Other organisations are unaffected.
    other = client.post("/api/auth/register", json={"email": "o@example.com", "password": "supersecret123", "organization_name": "Другая"}).json()
    assert client.get("/api/branding", headers={"Authorization": f"Bearer {other['access_token']}"}).json()["name"] is None
