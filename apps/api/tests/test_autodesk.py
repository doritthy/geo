"""Autodesk ACC / BIM 360 integration against a mock APS (httpx.MockTransport):
OAuth connect, hub browsing, one-click import of IFC and RVT (Model Derivative
-> IFC), webhook-driven re-import as a new model version, and RVT upload
conversion. The twin conversion of the downloaded files is real."""

import hashlib
import hmac
import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from tests.twin_fixtures import make_ifc

FOLDER = "urn:adsk.wipprod:fs.folder:co.FOLDER"
ITEM = "urn:adsk.wipprod:dm.lineage:ITEM"
RVT_ITEM = "urn:adsk.wipprod:dm.lineage:RVT"


class MockAPS:
    def __init__(self):
        self.versions = {ITEM: 1, RVT_ITEM: 1}
        self.calls: list[str] = []
        self.hooks: list[dict] = []
        self.ifc_v1 = make_ifc()
        self.ifc_v2 = make_ifc([("Стена 1", 0.0), ("Стена 2", 7.0), ("Стена 4", 18.0)])
        self.ifc_rvt = make_ifc([("Стена R", 0.0)])

    def version(self, item: str) -> dict:
        n = self.versions[item]
        name = "model.ifc" if item == ITEM else "house.rvt"
        key = f"{item.rsplit(':', 1)[-1]}-v{n}.{name.rsplit('.', 1)[-1]}"
        return {
            "type": "versions",
            "id": f"urn:adsk.wipprod:fs.file:vf.{item[-4:]}?version={n}",
            "attributes": {"name": name, "displayName": name},
            "relationships": {"storage": {"data": {"id": f"urn:adsk.objects:os.object:wip.dm.prod/{key}"}}},
        }

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        path = url.path
        self.calls.append(f"{request.method} {url.host}{path}")
        if path == "/authentication/v2/token":
            form = parse_qs(request.content.decode())
            assert request.headers["authorization"].startswith("Basic ")
            body = {"access_token": f"tok-{form['grant_type'][0]}", "token_type": "Bearer", "expires_in": 3599}
            if form["grant_type"][0] != "client_credentials":
                body["refresh_token"] = "refresh-1"
            return httpx.Response(200, json=body)
        if path == "/project/v1/hubs":
            return httpx.Response(200, json={"data": [{"type": "hubs", "id": "b.acc", "attributes": {"name": "BI Group"}}]})
        if path.endswith("/tip"):
            item = ITEM if "ITEM" in path else RVT_ITEM
            return httpx.Response(200, json={"data": self.version(item)})
        if path.endswith("/signeds3download"):
            obj = path.split("/objects/")[1].split("/")[0]
            return httpx.Response(200, json={"status": "complete", "url": f"https://s3.mock/{obj}"})
        if url.host == "s3.mock":
            assert "authorization" not in request.headers
            return httpx.Response(200, content=self.ifc_v1 if path.endswith("v1.ifc") else self.ifc_v2)
        if path == "/modelderivative/v2/designdata/job":
            return httpx.Response(200, json={"result": "success"})
        if path.endswith("/manifest") and "/designdata/" in path:
            return httpx.Response(200, json={
                "status": "success",
                "derivatives": [{"outputType": "ifc", "status": "success",
                                 "children": [{"urn": "urn:adsk.viewing:fs.file:X/output/house.ifc", "role": "ifc"}]}],
            })
        if path.endswith("/signedcookies"):
            return httpx.Response(
                200, json={"url": "https://cdn.mock/house.ifc"},
                headers=[("set-cookie", "CloudFront-Policy=p; Domain=cdn.mock; Path=/"),
                         ("set-cookie", "CloudFront-Signature=s; Domain=cdn.mock; Path=/")],
            )
        if url.host == "cdn.mock":
            assert "CloudFront-Policy=p" in request.headers.get("cookie", "")
            return httpx.Response(200, content=self.ifc_rvt)
        if path == "/oss/v2/buckets":
            return httpx.Response(200, json={"bucketKey": json.loads(request.content)["bucketKey"]})
        if path.endswith("/signeds3upload") and request.method == "GET":
            return httpx.Response(200, json={"uploadKey": "uk", "urls": ["https://s3.mock/upload"]})
        if url.host == "s3.mock" and request.method == "PUT":
            return httpx.Response(200)
        if path.endswith("/signeds3upload") and request.method == "POST":
            return httpx.Response(200, json={"objectId": "urn:adsk.objects:os.object:twin_x/house.rvt"})
        if path.endswith("/dm.version.added/hooks"):
            self.hooks.append(json.loads(request.content))
            return httpx.Response(201, headers={"Location": "https://developer.api.autodesk.com/webhooks/v1/hooks/HOOK1"})
        return httpx.Response(404, json={"error": f"unmocked {request.method} {url}"})


@pytest.fixture()
def aps(monkeypatch):
    from app.config import get_settings
    from app.integrations import aps as aps_mod
    from app.integrations import autodesk_service

    settings = get_settings()
    for key, value in {
        "APS_CLIENT_ID": "clientid", "APS_CLIENT_SECRET": "secret",
        "APS_WEBHOOK_URL": "https://twin.example/api/integrations/autodesk/webhook",
        "APS_WEBHOOK_SECRET": "hooksecret", "PUBLIC_WEB_URL": "http://web.test",
    }.items():
        monkeypatch.setattr(settings, key, value)
    mock = MockAPS()
    monkeypatch.setattr(autodesk_service, "client_factory", lambda: aps_mod.APSClient(transport=httpx.MockTransport(mock)))
    return mock


def _headers(client):
    resp = client.post("/api/auth/register", json={
        "email": "acc@example.com", "password": "supersecret123", "full_name": "ACC", "organization_name": "BI",
    })
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _connect(client, h):
    url = client.get("/api/integrations/autodesk/login", params={"return_to": "/twin/x"}, headers=h).json()["url"]
    parsed = urlparse(url)
    assert parsed.netloc == "developer.api.autodesk.com" and parsed.path == "/authentication/v2/authorize"
    state = parse_qs(parsed.query)["state"][0]
    resp = client.get("/api/integrations/autodesk/callback", params={"code": "abc", "state": state}, follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == "http://web.test/twin/x?autodesk=connected"


def test_not_configured(client):
    h = _headers(client)
    assert client.get("/api/integrations/autodesk/status", headers=h).json()["configured"] is False
    assert client.get("/api/integrations/autodesk/hubs", headers=h).status_code == 503


def test_connect_browse_import_and_webhook(client, aps):
    h = _headers(client)
    _connect(client, h)
    assert client.get("/api/integrations/autodesk/status", headers=h).json()["connected"] is True
    assert client.get("/api/integrations/autodesk/hubs", headers=h).json()[0]["name"] == "BI Group"

    pid = client.post("/api/projects", json={"name": "ACC"}, headers=h).json()["id"]
    resp = client.post(f"/api/projects/{pid}/autodesk/imports", headers=h, json={
        "hub_id": "b.acc", "aps_project_id": "b.proj", "item_id": ITEM, "folder_id": FOLDER, "name": "Корпус А",
    })
    assert resp.status_code == 201, resp.text
    links = client.get(f"/api/projects/{pid}/autodesk/imports", headers=h).json()
    assert links[0]["status"] == "ready", links[0]["error_message"]
    assert links[0]["watching"] is True
    assert aps.hooks[0]["scope"] == {"folder": FOLDER} and aps.hooks[0]["token"] == "hooksecret"

    assets = client.get(f"/api/projects/{pid}/assets", headers=h).json()
    assert [(a["name"], a["version"], a["stats"]["element_count"]) for a in assets] == [("Корпус А", 1, 3)]

    # Same version again -> no duplicate
    client.post(f"/api/projects/{pid}/autodesk/imports/{links[0]['id']}/sync", headers=h)
    assert len(client.get(f"/api/projects/{pid}/assets", headers=h).json()) == 1

    # New version published in ACC -> webhook -> version 2 in the same group
    aps.versions[ITEM] = 2
    body = json.dumps({"hook": {"hookAttribute": {"link": links[0]["id"]}},
                       "payload": {"lineageUrn": ITEM, "source": "urn:...?version=2", "ext": "ifc"}}).encode()
    bad = client.post("/api/integrations/autodesk/webhook", content=body, headers={"x-adsk-signature": "sha1hash=00"})
    assert bad.status_code == 401
    sig = "sha1hash=" + hmac.new(b"hooksecret", body, hashlib.sha1).hexdigest()
    resp = client.post("/api/integrations/autodesk/webhook", content=body, headers={"x-adsk-signature": sig})
    assert resp.json() == {"queued": 1}
    assets = client.get(f"/api/projects/{pid}/assets", headers=h).json()
    assert sorted(a["version"] for a in assets) == [1, 2]
    assert len({a["version_group"] for a in assets}) == 1
    diff = client.get(f"/api/assets/{assets[0]['id']}/compare", params={"other": assets[1]["id"]}, headers=h).json()
    assert diff["counts"]["added"] == 1 and diff["counts"]["removed"] == 1


def test_rvt_item_translated_to_ifc(client, aps):
    h = _headers(client)
    _connect(client, h)
    pid = client.post("/api/projects", json={"name": "ACC"}, headers=h).json()["id"]
    client.post(f"/api/projects/{pid}/autodesk/imports", headers=h, json={
        "aps_project_id": "b.proj", "item_id": RVT_ITEM, "name": "Дом", "watch": False,
    })
    link = client.get(f"/api/projects/{pid}/autodesk/imports", headers=h).json()[0]
    assert link["status"] == "ready", link["error_message"]
    assert any(c.endswith("/modelderivative/v2/designdata/job") for c in aps.calls)
    asset = client.get(f"/api/projects/{pid}/assets", headers=h).json()[0]
    assert asset["kind"] == "bim" and asset["stats"]["element_count"] == 1


def test_rvt_upload_uses_model_derivative(client, aps):
    h = _headers(client)
    pid = client.post("/api/projects", json={"name": "RVT"}, headers=h).json()["id"]
    resp = client.post(f"/api/projects/{pid}/files", data={"category": "bim"}, files={"file": ("house.rvt", b"RVT")}, headers=h)
    record = client.get(f"/api/files/{resp.json()['id']}", headers=h).json()
    assert record["status"] == "ready", record["error_message"]
    assert any("/oss/v2/buckets" in c for c in aps.calls)
