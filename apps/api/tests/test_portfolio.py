"""Portfolio analytics: key figures of every visible project side by side."""

from datetime import date, timedelta

from scripts.make_demo_data import make_schedule_xml
from tests.test_issues import _admin, _worker


def test_portfolio_compares_projects(client):
    h = _admin(client)
    ids = [client.post("/api/projects", json={"name": n}, headers=h).json()["id"] for n in ("Корпус А", "Корпус Б", "Мост")]
    client.post(f"/api/projects/{ids[0]}/schedule/import", headers=h, files={"file": ("p.xml", make_schedule_xml(storeys=3))})
    for title, due in (("Трещина", date.today() - timedelta(days=2)), ("Мусор", None)):
        client.post(f"/api/projects/{ids[1]}/issues", headers=h, json={"title": title, **({"due_date": str(due)} if due else {})})
    s = client.post(f"/api/projects/{ids[2]}/sensors", headers=h, json={"code": "TL", "name": "Пилон", "warn_max": 1}).json()
    client.post("/api/iot/ingest", headers={"X-Sensor-Token": s["ingest_token"]}, json={"value": 2})

    data = client.get("/api/portfolio", headers=h).json()
    by = {p["name"]: p for p in data["projects"]}
    assert set(by) == {"Корпус А", "Корпус Б", "Мост"}
    assert by["Корпус А"]["schedule"]["tasks"] > 0 and by["Корпус А"]["schedule"]["spi"] is not None
    assert by["Корпус Б"]["schedule"] is None
    assert by["Корпус Б"]["issues"] == {"open": 2, "overdue": 1}
    assert by["Мост"]["sensors"] == {"warn": 1}

    # A regular member only sees the projects they belong to.
    _, wh = _worker(client, h, ids[1])
    assert [p["name"] for p in client.get("/api/portfolio", headers=wh).json()["projects"]] == ["Корпус Б"]
