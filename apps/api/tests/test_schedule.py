"""4D plan-fact: MS Project XML / Excel import, task-element links, SPI,
element statuses, progress from a deviation analysis."""

import io
import json
from datetime import date

import pytest

from scripts.make_demo_data import make_building, make_scan, make_schedule_xml


def _headers(client):
    r = client.post("/api/auth/register", json={"email": "pm@example.com", "password": "supersecret123",
                                                "full_name": "PM", "organization_name": "BI"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _upload(client, h, pid, name, data, category):
    r = client.post(f"/api/projects/{pid}/files", headers=h, files={"file": (name, data)}, data={"category": category})
    rec = client.get(f"/api/files/{r.json()['id']}", headers=h).json()
    assert rec["status"] == "ready", rec["error_message"]
    return rec["metadata"]["asset_id"]


def test_msproject_import_links_metrics(client):
    h = _headers(client)
    pid = client.post("/api/projects", json={"name": "4D"}, headers=h).json()["id"]
    r = client.post(f"/api/projects/{pid}/schedule/import", headers=h, files={"file": ("plan.xml", make_schedule_xml(storeys=3))})
    assert r.status_code == 200, r.text
    tasks = r.json()["tasks"]
    assert tasks[0]["name"] == "Корпус А" and tasks[0]["is_summary"]
    leaves = [t for t in tasks if not t["is_summary"]]
    assert len(leaves) == 9 and all(t["parent_id"] for t in leaves)

    sched = client.get(f"/api/projects/{pid}/schedule", params={"on": "2026-05-20"}, headers=h).json()
    m = sched["metrics"]
    assert m["weight"] == "cost" and 0 < m["spi"] < 2 and m["forecast_finish"]
    by_name = {t["name"]: t for t in sched["tasks"]}
    assert by_name["Каркас: колонны и плита — этаж 1"]["status"] == "done"
    assert by_name["Остекление — этаж 3"]["status"] in ("late", "not_started", "future")
    floor1 = by_name["Этаж 1"]
    assert floor1["percent_complete"] == pytest.approx(100.0)

    bim = _upload(client, h, pid, "b.ifc", make_building(storeys=3), "bim")
    frame = by_name["Каркас: колонны и плита — этаж 2"]["id"]
    for cls in ("IfcColumn", "IfcSlab"):
        client.post(f"/api/schedule/tasks/{frame}/elements", headers=h, json={"asset_id": bim, "ifc_type": cls, "storey": "Этаж 2"})
    glazing = by_name["Остекление — этаж 3"]["id"]
    r = client.post(f"/api/schedule/tasks/{glazing}/elements", headers=h, json={"asset_id": bim, "ifc_type": "IfcWindow", "storey": "Этаж 3"})
    assert r.json()["linked"] > 0
    st = client.get(f"/api/projects/{pid}/schedule/element-status", params={"asset_id": bim, "on": "2026-05-20"}, headers=h).json()["statuses"]
    assert set(st.values()) <= {"done", "late", "not_started", "future", "in_progress"}
    assert "done" in st.values()

    # Re-import keeps links (matched by UID)
    client.post(f"/api/projects/{pid}/schedule/import", headers=h, files={"file": ("plan.xml", make_schedule_xml(storeys=3))})
    again = {t["name"]: t for t in client.get(f"/api/projects/{pid}/schedule", headers=h).json()["tasks"]}
    assert again["Каркас: колонны и плита — этаж 2"]["element_count"] > 0

    # Manual progress update
    tid = again["Наружные стены — этаж 3"]["id"]
    assert client.patch(f"/api/schedule/tasks/{tid}", headers=h, json={"percent_complete": 90}).json()["percent_complete"] == 90
    assert client.patch(f"/api/schedule/tasks/{again['Этаж 1']['id']}", headers=h, json={"percent_complete": 5}).status_code == 400


def test_excel_import_and_progress_from_scan(client):
    from openpyxl import Workbook

    h = _headers(client)
    pid = client.post("/api/projects", json={"name": "4D"}, headers=h).json()["id"]
    wb = Workbook()
    ws = wb.active
    ws.append(["Шифр", "Наименование", "Начало", "Окончание", "% выполнения"])
    ws.append(["1", "Стены этажа 1", date(2026, 3, 1), date(2026, 3, 31), 0.0])
    ws.append(["2", "Стены этажа 3", date(2026, 4, 1), date(2026, 4, 30), 0.0])
    buf = io.BytesIO()
    wb.save(buf)
    tasks = client.post(f"/api/projects/{pid}/schedule/import", headers=h, files={"file": ("plan.xlsx", buf.getvalue())}).json()["tasks"]
    assert [t["name"] for t in tasks] == ["Стены этажа 1", "Стены этажа 3"]

    bim = _upload(client, h, pid, "b.ifc", make_building(storeys=3), "bim")
    scan = _upload(client, h, pid, "s.laz", make_scan(storeys_built=2, spacing=0.25), "point_cloud")
    for t, storey in zip(tasks, ("Этаж 1", "Этаж 3")):
        client.post(f"/api/schedule/tasks/{t['id']}/elements", headers=h, json={"asset_id": bim, "ifc_type": "IfcWall", "storey": storey})
    a = client.post(f"/api/projects/{pid}/analyses/deviation", headers=h, json={"cloud_asset_id": scan, "bim_asset_id": bim}).json()
    assert client.get(f"/api/analyses/{a['id']}", headers=h).json()["status"] == "ready"
    res = client.post(f"/api/projects/{pid}/schedule/progress-from-analysis", headers=h, json={"analysis_id": a["id"]}).json()
    pct = {t["name"]: t["percent_complete"] for t in res["tasks"]}
    assert pct["Стены этажа 1"] == 100.0  # scanned
    assert pct["Стены этажа 3"] == 0.0  # not built yet


def test_bad_files(client):
    h = _headers(client)
    pid = client.post("/api/projects", json={"name": "4D"}, headers=h).json()["id"]
    r = client.post(f"/api/projects/{pid}/schedule/import", headers=h, files={"file": ("plan.mpp", b"\xd0\xcf")})
    assert r.status_code == 400 and "XML" in r.json()["detail"]
    r = client.post(f"/api/projects/{pid}/schedule/import", headers=h, files={"file": ("plan.xml", b"<x/>")})
    assert r.status_code == 400


def test_dashboard(client):
    h = _headers(client)
    pid = client.post("/api/projects", json={"name": "Dash"}, headers=h).json()["id"]
    empty = client.get(f"/api/projects/{pid}/dashboard", headers=h).json()
    assert empty["schedule"] is None and empty["issues"]["total"] == 0 and empty["quality"] is None
    client.post(f"/api/projects/{pid}/schedule/import", headers=h, files={"file": ("plan.xml", make_schedule_xml(storeys=2))})
    client.post(f"/api/projects/{pid}/issues", headers=h, json={"title": "A", "due_date": "2020-01-01"})
    d = client.get(f"/api/projects/{pid}/dashboard", headers=h).json()
    assert d["schedule"]["tasks"] == 6
    assert d["issues"]["open"] == 1 and d["issues"]["overdue"] == 1 and d["issues"]["overdue_list"][0]["number"] == 1


def test_forecast_after_planned_finish_is_not_in_the_past():
    from datetime import date
    from types import SimpleNamespace

    from app.twin.schedule import metrics

    # Planned Jan–Mar, 60 % done, status date in June: PV is saturated.
    t = SimpleNamespace(is_summary=False, cost=None, start_date=date(2026, 1, 1), finish_date=date(2026, 3, 31), percent_complete=60)
    on = date(2026, 6, 1)
    m = metrics([t], on)
    f = date.fromisoformat(m["forecast_finish"])
    assert f > on
    # 60 % in 151 days -> remaining 40 % needs ~101 more days.
    assert 95 <= (f - on).days <= 105
    assert m["delay_days"] == (f - date(2026, 3, 31)).days
