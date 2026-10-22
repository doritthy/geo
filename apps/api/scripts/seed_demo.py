"""Fill a running platform with the demo project through the public API:
two IFC versions, the as-built scan, the site boundary, an annotation, a
4D schedule linked to the model and a deviation analysis.

    python scripts/make_demo_data.py demo_data
    python scripts/seed_demo.py --api http://localhost:8000 --data demo_data

Then log in at http://localhost:3000 with the printed credentials.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import httpx


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--data", default="demo_data")
    ap.add_argument("--email", default="demo@example.com")
    ap.add_argument("--password", default="demo12345")
    args = ap.parse_args()

    c = httpx.Client(base_url=args.api, timeout=300)
    r = c.post("/api/auth/register", json={"email": args.email, "password": args.password,
                                           "full_name": "Демо Пользователь", "organization_name": "Демо"})
    if r.status_code != 200:
        r = c.post("/api/auth/login", json={"email": args.email, "password": args.password})
    r.raise_for_status()
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}

    pid = c.post("/api/projects", headers=h, json={
        "name": "ЖК Демо — Корпус А", "description": "BIM + лазерный скан + граница участка", "crs": "EPSG:32642",
    }).json()["id"]

    def upload(name: str, category: str, options: dict) -> str | None:
        with open(os.path.join(args.data, name), "rb") as fh:
            f = c.post(f"/api/projects/{pid}/files", headers=h, data={"category": category, "options": json.dumps(options)},
                       files={"file": (name, fh)}).json()
        for _ in range(600):
            rec = c.get(f"/api/files/{f['id']}", headers=h).json()
            if rec["status"] in ("ready", "error"):
                break
            time.sleep(1)
        print(f"{name}: {rec['status']} {rec.get('error_message') or ''}")
        if rec["status"] != "ready":
            sys.exit(1)
        return rec["metadata"].get("asset_id")

    v1 = upload("demo_building_v1.ifc", "bim", {"name": "Корпус А — АР/КР", "captured_at": "2026-03-01"})
    v2 = upload("demo_building_v2.ifc", "bim", {"name": "Корпус А — АР/КР", "replaces_asset_id": v1, "captured_at": "2026-06-01"})
    scan = upload("demo_scan.laz", "point_cloud", {"name": "Лазерное сканирование", "captured_at": "2026-05-20"})
    upload("demo_site.geojson", "map_vector", {})
    upload("demo_ortho.tif", "map_raster", {"name": "Ортофотоплан 20.05.2026"})

    center = c.get(f"/api/assets/{v2}", headers=h).json()["stats"]["center"]
    c.post(f"/api/projects/{pid}/annotations", headers=h, json={
        "longitude": center["longitude"], "latitude": center["latitude"], "height": center["height"] + 9,
        "title": "Проверить плиту 3-го этажа", "body": "По скану возможен прогиб", "asset_id": v2,
    })

    # 4D: schedule + links (per storey: frame -> columns & slab, walls, glazing)
    with open(os.path.join(args.data, "demo_schedule.xml"), "rb") as fh:
        tasks = c.post(f"/api/projects/{pid}/schedule/import", headers=h, files={"file": ("demo_schedule.xml", fh)}).json()["tasks"]
    classes = {"Каркас": ("IfcColumn", "IfcSlab"), "Наружные стены": ("IfcWall",), "Остекление": ("IfcWindow",)}
    for t in tasks:
        if t["is_summary"] or "этаж" not in t["name"]:
            continue
        prefix, storey_no = t["name"].split(" — этаж ")
        for cls in next(v for k, v in classes.items() if prefix.startswith(k)):
            c.post(f"/api/schedule/tasks/{t['id']}/elements", headers=h,
                   json={"asset_id": v2, "ifc_type": cls, "storey": f"Этаж {storey_no}"})
    print(f"schedule: {len(tasks)} tasks")

    a = c.post(f"/api/projects/{pid}/analyses/deviation", headers=h,
               json={"cloud_asset_id": scan, "bim_asset_id": v1}).json()
    for _ in range(600):
        a = c.get(f"/api/analyses/{a['id']}", headers=h).json()
        if a["status"] in ("ready", "error"):
            break
        time.sleep(1)
    print(f"deviation analysis: {a['status']} {a.get('error_message') or ''}")

    # IoT: demo sensors with a week of history
    import subprocess

    subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "iot_simulator.py"), "--api", args.api,
                    "--project", pid, "--email", args.email, "--password", args.password], check=False)
    print(f"\nГотово. Вход: {args.email} / {args.password}; проект {pid}")


if __name__ == "__main__":
    main()
