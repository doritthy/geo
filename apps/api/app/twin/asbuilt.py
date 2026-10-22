"""As-built BIM: the source IFC with a per-element property set from a
deviation analysis (ТЗ Фаза 3: «актуализация BIM по данным сканирования,
экспорт IFC»).

Property set `Twin_AsBuilt` (custom psets must not use the reserved `Pset_`
prefix): Status, AnalysisDate, ScanName, ScanPoints, DeviationMean_mm,
DeviationP95_mm, DeviationMax_mm, OutOfTolerance_pct, Tolerance_mm.
Geometry is not changed — the IFC stays the design model, annotated with
how the built element compares to it.
"""

from __future__ import annotations

import os
import tempfile

PSET = "Twin_AsBuilt"
MIN_POINTS = 20

STATUS_OK = "Соответствует проекту"
STATUS_DEVIATION = "Отклонение сверх допуска"
STATUS_FEW = "Недостаточно точек скана"
STATUS_NONE = "Не отсканировано"


def element_status(row: dict | None, tol_m: float) -> str:
    if row is None:
        return STATUS_NONE
    if row["points"] < MIN_POINTS:
        return STATUS_FEW
    return STATUS_OK if row["p95_abs"] <= tol_m else STATUS_DEVIATION


def build_as_built(src_path: str, result: dict, analysis_date: str) -> tuple[bytes, dict]:
    """Returns (IFC bytes, counts per status)."""
    import ifcopenshell
    import ifcopenshell.api

    model = ifcopenshell.open(src_path)
    tol_m = float(result["tolerances"][1])
    rows = {e["global_id"]: e for e in result.get("elements", [])}
    scan = (result.get("cloud") or {}).get("name", "")
    restore = _ifc2x3_owner(model) if model.schema == "IFC2X3" else None
    try:
        counts = _annotate(model, rows, tol_m, scan, analysis_date)
    finally:
        if restore:
            restore()
    fd, out = tempfile.mkstemp(suffix=".ifc")
    os.close(fd)
    try:
        model.write(out)
        with open(out, "rb") as fh:
            return fh.read(), counts
    finally:
        os.unlink(out)


def _ifc2x3_owner(model):
    """IFC2X3 requires an IfcOwnerHistory on every new rooted entity;
    IfcOpenShell asks callbacks for the user and application."""
    import ifcopenshell.api
    import ifcopenshell.api.owner.settings as ows

    po = (model.by_type("IfcPersonAndOrganization") or [None])[0]
    if po is None:
        person = ifcopenshell.api.run("owner.add_person", model, identification="twin", family_name="Twin")
        org = ifcopenshell.api.run("owner.add_organisation", model, identification="twin", name="Digital Twin")
        po = ifcopenshell.api.run("owner.add_person_and_organisation", model, person=person, organisation=org)
    app = (model.by_type("IfcApplication") or [None])[0] or ifcopenshell.api.run("owner.add_application", model)
    old = (ows.get_user, ows.get_application)
    ows.get_user, ows.get_application = (lambda f: po), (lambda f: app)

    def restore():
        ows.get_user, ows.get_application = old
    return restore


def _annotate(model, rows: dict, tol_m: float, scan: str, analysis_date: str) -> dict[str, int]:
    import ifcopenshell.api

    counts: dict[str, int] = {}
    for el in model.by_type("IfcElement"):
        if el.is_a("IfcOpeningElement") or el.is_a("IfcVirtualElement"):
            continue
        row = rows.get(el.GlobalId)
        status = element_status(row, tol_m)
        counts[status] = counts.get(status, 0) + 1
        props: dict = {"Status": status, "AnalysisDate": analysis_date, "ScanName": scan, "Tolerance_mm": round(tol_m * 1000, 1)}
        if row is not None:
            props.update({
                "ScanPoints": int(row["points"]),
                "DeviationMean_mm": round(row["mean"] * 1000, 1),
                "DeviationP95_mm": round(row["p95_abs"] * 1000, 1),
                "DeviationMax_mm": round(row["max_abs"] * 1000, 1),
                "OutOfTolerance_pct": round(row["out_of_tolerance"] * 100, 1),
            })
        pset = ifcopenshell.api.run("pset.add_pset", model, product=el, name=PSET)
        ifcopenshell.api.run("pset.edit_pset", model, pset=pset, properties=props)
    return counts
