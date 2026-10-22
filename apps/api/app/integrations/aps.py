"""Thin Autodesk Platform Services (APS) client: OAuth v2, Data Management
(hubs / projects / folders / items / versions), OSS signed S3 transfers,
Model Derivative (RVT/NWD/DWG -> IFC) and Webhooks.

Pure HTTP via httpx; the transport is injectable so the flows are unit
tested against a mock APS (tests/test_autodesk.py).
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from urllib.parse import quote, urlencode

import httpx

from app.config import get_settings

SCOPES_3LEGGED = "data:read data:write data:create viewables:read"
SCOPES_2LEGGED = "data:read data:write data:create bucket:create bucket:read viewables:read"

# File types that are converted to IFC by Model Derivative before ingestion.
TRANSLATE_TO_IFC = ("rvt", "rfa", "nwd", "nwc", "dwg", "ifczip")
NATIVE = ("ifc", "las", "laz", "e57", "obj", "glb", "gltf", "ply", "zip")


class APSError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass
class Token:
    access_token: str
    expires_at: float
    refresh_token: str | None = None


def urn_b64(urn: str) -> str:
    """Model Derivative URN: URL-safe base64 without padding."""
    return base64.urlsafe_b64encode(urn.encode()).decode().rstrip("=")


def parse_storage_urn(urn: str) -> tuple[str, str]:
    """'urn:adsk.objects:os.object:wip.dm.prod/abc.rvt' -> (bucket, object)."""
    prefix = "urn:adsk.objects:os.object:"
    if not urn.startswith(prefix) or "/" not in urn[len(prefix):]:
        raise APSError(f"Unexpected storage URN: {urn}")
    bucket, obj = urn[len(prefix):].split("/", 1)
    return bucket, obj


class APSClient:
    def __init__(self, transport: httpx.BaseTransport | None = None):
        self.settings = get_settings()
        self.base = self.settings.APS_BASE_URL.rstrip("/")
        self.http = httpx.Client(transport=transport, timeout=httpx.Timeout(60.0, connect=15.0), follow_redirects=True)
        self._app_token: Token | None = None

    # ---------- OAuth ----------

    def authorize_url(self, state: str) -> str:
        params = {
            "response_type": "code",
            "client_id": self.settings.APS_CLIENT_ID,
            "redirect_uri": self.settings.APS_CALLBACK_URL,
            "scope": SCOPES_3LEGGED,
            "state": state,
        }
        return f"{self.base}/authentication/v2/authorize?{urlencode(params)}"

    def _token_request(self, data: dict) -> Token:
        resp = self.http.post(
            f"{self.base}/authentication/v2/token",
            data=data,
            auth=(self.settings.APS_CLIENT_ID, self.settings.APS_CLIENT_SECRET),
            headers={"Accept": "application/json"},
        )
        if resp.status_code != 200:
            raise APSError(f"Autodesk OAuth error: {resp.text[:300]}", resp.status_code)
        body = resp.json()
        return Token(
            access_token=body["access_token"],
            expires_at=time.time() + float(body.get("expires_in", 3600)) - 60,
            refresh_token=body.get("refresh_token"),
        )

    def exchange_code(self, code: str) -> Token:
        return self._token_request(
            {"grant_type": "authorization_code", "code": code, "redirect_uri": self.settings.APS_CALLBACK_URL}
        )

    def refresh(self, refresh_token: str) -> Token:
        return self._token_request({"grant_type": "refresh_token", "refresh_token": refresh_token, "scope": SCOPES_3LEGGED})

    def app_token(self) -> str:
        """2-legged token (our own app's OSS bucket, Model Derivative)."""
        if self._app_token is None or self._app_token.expires_at < time.time():
            self._app_token = self._token_request({"grant_type": "client_credentials", "scope": SCOPES_2LEGGED})
        return self._app_token.access_token

    # ---------- helpers ----------

    def _get(self, token: str, path: str, **kw) -> dict:
        resp = self.http.get(f"{self.base}{path}", headers={"Authorization": f"Bearer {token}"}, **kw)
        if resp.status_code >= 400:
            raise APSError(f"GET {path}: {resp.status_code} {resp.text[:300]}", resp.status_code)
        return resp.json()

    def _post(self, token: str, path: str, json: dict, headers: dict | None = None) -> httpx.Response:
        resp = self.http.post(
            f"{self.base}{path}", json=json,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", **(headers or {})},
        )
        if resp.status_code >= 400:
            raise APSError(f"POST {path}: {resp.status_code} {resp.text[:300]}", resp.status_code)
        return resp

    # ---------- Data Management ----------

    def hubs(self, token: str) -> list[dict]:
        return self._get(token, "/project/v1/hubs").get("data", [])

    def projects(self, token: str, hub_id: str) -> list[dict]:
        return self._get(token, f"/project/v1/hubs/{quote(hub_id, safe='')}/projects").get("data", [])

    def top_folders(self, token: str, hub_id: str, project_id: str) -> list[dict]:
        return self._get(
            token, f"/project/v1/hubs/{quote(hub_id, safe='')}/projects/{quote(project_id, safe='')}/topFolders"
        ).get("data", [])

    def folder_contents(self, token: str, project_id: str, folder_id: str) -> list[dict]:
        return self._get(
            token, f"/data/v1/projects/{quote(project_id, safe='')}/folders/{quote(folder_id, safe='')}/contents"
        ).get("data", [])

    def item(self, token: str, project_id: str, item_id: str) -> dict:
        return self._get(token, f"/data/v1/projects/{quote(project_id, safe='')}/items/{quote(item_id, safe='')}")

    def tip_version(self, token: str, project_id: str, item_id: str) -> dict:
        return self._get(
            token, f"/data/v1/projects/{quote(project_id, safe='')}/items/{quote(item_id, safe='')}/tip"
        )["data"]

    # ---------- OSS transfers ----------

    def download_object(self, token: str, storage_urn: str, dest_path: str) -> None:
        bucket, obj = parse_storage_urn(storage_urn)
        info = self._get(
            token, f"/oss/v2/buckets/{quote(bucket, safe='')}/objects/{quote(obj, safe='')}/signeds3download"
        )
        url = info.get("url")
        if not url:
            raise APSError("Signed download URL missing in APS response")
        self._stream_to(url, dest_path)

    def _stream_to(self, url: str, dest_path: str, headers: dict | None = None) -> None:
        with self.http.stream("GET", url, headers=headers) as resp:
            if resp.status_code >= 400:
                raise APSError(f"Download failed: {resp.status_code}", resp.status_code)
            with open(dest_path, "wb") as fh:
                for chunk in resp.iter_bytes(1024 * 1024):
                    fh.write(chunk)

    def ensure_bucket(self, bucket: str) -> None:
        token = self.app_token()
        resp = self.http.post(
            f"{self.base}/oss/v2/buckets",
            json={"bucketKey": bucket, "policyKey": "transient"},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        if resp.status_code not in (200, 409):  # 409 = already exists
            raise APSError(f"Bucket create failed: {resp.status_code} {resp.text[:200]}", resp.status_code)

    def upload_object(self, bucket: str, object_key: str, path: str) -> str:
        """Single-part signed S3 upload (fine up to ~5 GB). Returns objectId URN."""
        token = self.app_token()
        q = f"/oss/v2/buckets/{quote(bucket, safe='')}/objects/{quote(object_key, safe='')}/signeds3upload"
        info = self._get(token, q)
        with open(path, "rb") as fh:
            put = self.http.put(info["urls"][0], content=fh.read())
        if put.status_code >= 400:
            raise APSError(f"S3 upload failed: {put.status_code}", put.status_code)
        done = self._post(token, q, {"uploadKey": info["uploadKey"]})
        return done.json()["objectId"]

    # ---------- Model Derivative ----------

    def translate_to_ifc(self, token: str, source_urn: str, force: bool = False) -> str:
        """Starts an IFC translation; returns the base64 URN to poll.

        `force` (x-ads-force) deletes existing derivatives -- only for objects
        in our own bucket, never for ACC versions (it would wipe ACC's views)."""
        b64 = urn_b64(source_urn)
        self._post(
            token,
            "/modelderivative/v2/designdata/job",
            {
                "input": {"urn": b64},
                "output": {"formats": [{"type": "ifc", "advanced": {"exportSettingName": "IFC4 Reference View"}}]},
            },
            headers={"x-ads-force": "true"} if force else None,
        )
        return b64

    def manifest(self, token: str, b64_urn: str) -> dict:
        return self._get(token, f"/modelderivative/v2/designdata/{b64_urn}/manifest")

    @staticmethod
    def find_ifc_derivative(manifest: dict) -> str | None:
        for deriv in manifest.get("derivatives", []):
            if deriv.get("outputType") != "ifc":
                continue
            stack = list(deriv.get("children", []))
            while stack:
                child = stack.pop()
                urn = child.get("urn")
                if urn and urn.lower().endswith(".ifc"):
                    return urn
                stack.extend(child.get("children", []))
        return None

    def wait_for_ifc(self, token: str, b64_urn: str, timeout_s: float = 1800, poll_s: float = 10) -> str:
        deadline = time.time() + timeout_s
        while True:
            mf = self.manifest(token, b64_urn)
            status = mf.get("status")
            if status == "success":
                urn = self.find_ifc_derivative(mf)
                if not urn:
                    raise APSError("Translation finished without an IFC derivative")
                return urn
            if status in ("failed", "timeout"):
                messages = [m.get("message") for d in mf.get("derivatives", []) for m in d.get("messages", []) if m]
                raise APSError(f"Model Derivative translation {status}: {'; '.join(map(str, messages))[:500]}")
            if time.time() > deadline:
                raise APSError("Model Derivative translation timed out")
            time.sleep(poll_s)

    def download_derivative(self, token: str, b64_urn: str, derivative_urn: str, dest_path: str) -> None:
        resp = self.http.get(
            f"{self.base}/modelderivative/v2/designdata/{b64_urn}/manifest/{quote(derivative_urn, safe='')}/signedcookies",
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code >= 400:
            raise APSError(f"Derivative download link failed: {resp.status_code} {resp.text[:200]}", resp.status_code)
        url = resp.json()["url"]
        # CloudFront-* cookies are set for the CDN domain, not the API host, so a
        # cookie jar would drop them; forward the raw name=value pairs instead.
        pairs = [h.split(";", 1)[0].strip() for h in resp.headers.get_list("set-cookie")]
        cookie = "; ".join(p for p in pairs if "=" in p)
        self._stream_to(url, dest_path, headers={"Cookie": cookie} if cookie else None)

    # ---------- Webhooks ----------

    def create_version_hook(self, token: str, folder_urn: str, callback_url: str, attributes: dict) -> str | None:
        body = {"callbackUrl": callback_url, "scope": {"folder": folder_urn}, "hookAttribute": attributes}
        if self.settings.APS_WEBHOOK_SECRET:
            body["token"] = self.settings.APS_WEBHOOK_SECRET  # signs callbacks (x-adsk-signature)
        resp = self.http.post(
            f"{self.base}/webhooks/v1/systems/data/events/dm.version.added/hooks",
            json=body,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        if resp.status_code == 409:  # hook already exists for this folder/callback
            return None
        if resp.status_code >= 400:
            raise APSError(f"Webhook create failed: {resp.status_code} {resp.text[:200]}", resp.status_code)
        location = resp.headers.get("Location", "")
        return location.rstrip("/").rsplit("/", 1)[-1] or None

    # ---------- ACC Issues (construction/issues/v1; 3-legged only) ----------

    @staticmethod
    def acc_project_id(project_id: str) -> str:
        """Data Management ids carry a 'b.' prefix; the Issues API wants the bare UUID."""
        return project_id[2:] if project_id.startswith("b.") else project_id

    def issue_subtypes(self, token: str, project_id: str) -> list[dict]:
        pid = self.acc_project_id(project_id)
        body = self._get(token, f"/construction/issues/v1/projects/{pid}/issue-types",
                         params={"include": "subtypes", "filter[isActive]": "true"})
        out = []
        for t in body.get("results", []):
            for st in t.get("subtypes", []):
                if st.get("isActive", True):
                    out.append({"id": st["id"], "title": f"{t.get('title', '')} / {st.get('title', '')}".strip(" /")})
        return out

    def list_issues(self, token: str, project_id: str, updated_since: str | None = None) -> list[dict]:
        pid = self.acc_project_id(project_id)
        out, offset = [], 0
        while True:
            params = {"limit": 100, "offset": offset, "sortBy": "updatedAt"}
            if updated_since:
                params["filter[updatedAt]"] = f"{updated_since}.."
            body = self._get(token, f"/construction/issues/v1/projects/{pid}/issues", params=params)
            results = body.get("results", [])
            out.extend(results)
            total = body.get("pagination", {}).get("totalResults", len(out))
            offset += len(results)
            if not results or offset >= total:
                return out

    def create_issue(self, token: str, project_id: str, body: dict) -> dict:
        pid = self.acc_project_id(project_id)
        return self._post(token, f"/construction/issues/v1/projects/{pid}/issues", body).json()

    def update_issue(self, token: str, project_id: str, issue_id: str, body: dict) -> dict:
        pid = self.acc_project_id(project_id)
        resp = self.http.patch(
            f"{self.base}/construction/issues/v1/projects/{pid}/issues/{issue_id}", json=body,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        if resp.status_code >= 400:
            raise APSError(f"PATCH issue {issue_id}: {resp.status_code} {resp.text[:300]}", resp.status_code)
        return resp.json()
