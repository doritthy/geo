"""Executive elevation scheme (исполнительная схема отметок верха плит).

For each slab: a grid of control points on the design top face (from the
BIM triangles), the design elevation there, the as-built elevation from the
scan (median of points within a small horizontal radius, in a band around
the top face) and the deviation. Rendered as one PDF page per slab: plan
with numbered points coloured by deviation, plus a table with coordinates
in the project CRS and elevations in the model's height system.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
from scipy.spatial import cKDTree

INSET = 0.3  # m from the slab edge
RADII = (0.15, 0.35)  # m, horizontal search radius; widened for sparse scans
BAND = 0.20  # m, vertical band around the design top face
MIN_POINTS = 5


@dataclass
class ControlPoint:
    n: int
    local: tuple[float, float, float]  # design point, local ENU metres
    design_z: float
    actual_z: float | None
    count: int


@dataclass
class SlabScheme:
    global_id: str
    name: str
    storey: str | None
    points: list[ControlPoint] = field(default_factory=list)
    outline: list[tuple[tuple[float, float], tuple[float, float]]] = field(default_factory=list)


def fmt_dev(d_mm: float | None) -> str:
    if d_mm is None:
        return "—"
    r = int(round(d_mm))
    return "0" if r == 0 else f"{r:+d}"


def _top_faces(tris: np.ndarray) -> np.ndarray:
    n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    ln = np.linalg.norm(n, axis=1)
    ok = ln > 1e-12
    up = np.zeros(len(tris), dtype=bool)
    up[ok] = n[ok, 2] / ln[ok] > 0.9
    top = tris[up]
    if len(top) == 0:
        return top
    zc = top[:, :, 2].mean(axis=1)
    return top[zc > zc.max() - 0.3]  # the upper face, not ledges further down


def _boundary(top: np.ndarray) -> list:
    """Edges used by exactly one top triangle = the slab outline (and openings)."""
    q = np.round(top[:, :, :2], 3)
    count: dict = {}
    for t in q:
        for a, b in ((0, 1), (1, 2), (2, 0)):
            k = tuple(sorted((tuple(t[a]), tuple(t[b]))))
            count[k] = count.get(k, 0) + 1
    return [k for k, c in count.items() if c == 1]


def _design_z(top: np.ndarray, xy: np.ndarray) -> np.ndarray:
    """Height of the top face above each xy (NaN outside, e.g. openings)."""
    out = np.full(len(xy), np.nan)
    a, b, c = top[:, 0], top[:, 1], top[:, 2]
    v0, v1 = (b - a)[:, :2], (c - a)[:, :2]
    den = v0[:, 0] * v1[:, 1] - v1[:, 0] * v0[:, 1]
    for i, p in enumerate(xy):
        v2 = p - a[:, :2]
        with np.errstate(divide="ignore", invalid="ignore"):
            u = (v2[:, 0] * v1[:, 1] - v1[:, 0] * v2[:, 1]) / den
            v = (v0[:, 0] * v2[:, 1] - v2[:, 0] * v0[:, 1]) / den
        inside = (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1 + 1e-9) & np.isfinite(u)
        if inside.any():
            j = np.flatnonzero(inside)
            z = a[j, 2] + u[j] * (b[j, 2] - a[j, 2]) + v[j] * (c[j, 2] - a[j, 2])
            out[i] = z.max()
    return out


def compute(tris: np.ndarray, feature: np.ndarray, elements: list[tuple[int, str, str, str | None]],
            pts: np.ndarray, step: float) -> list[SlabScheme]:
    """`tris`/`pts` in a local ENU frame (metres); `elements`: (feature
    index, GlobalId, name, storey) of the slabs to survey."""
    slabs = []
    for idx, gid, name, storey in elements:
        top = _top_faces(tris[feature == idx])
        if len(top) == 0:
            continue
        s = SlabScheme(global_id=gid, name=name, storey=storey, outline=_boundary(top))
        lo, hi = top[:, :, :2].reshape(-1, 2).min(axis=0), top[:, :, :2].reshape(-1, 2).max(axis=0)
        xs = np.arange(lo[0] + INSET, hi[0] - INSET + 1e-6, step)
        ys = np.arange(lo[1] + INSET, hi[1] - INSET + 1e-6, step)
        if len(xs) == 0 or len(ys) == 0:
            continue
        gx, gy = np.meshgrid(xs, ys[::-1])  # rows from north to south, as on a drawing
        xy = np.column_stack([gx.ravel(), gy.ravel()])
        dz = _design_z(top, xy)
        ztop = float(top[:, :, 2].max())
        near = pts[(pts[:, 2] > ztop - BAND - 0.1) & (pts[:, 2] < ztop + BAND)
                   & (pts[:, 0] >= lo[0] - 1) & (pts[:, 0] <= hi[0] + 1) & (pts[:, 1] >= lo[1] - 1) & (pts[:, 1] <= hi[1] + 1)]
        tree = cKDTree(near[:, :2]) if len(near) else None
        n = 0
        for (x, y), z in zip(xy, dz):
            if not np.isfinite(z):
                continue
            n += 1
            actual, count = None, 0
            for radius in RADII if tree is not None else ():
                idxs = tree.query_ball_point((x, y), radius)
                zz = near[idxs, 2] if idxs else np.empty(0)
                zz = zz[np.abs(zz - z) < BAND]
                count = int(len(zz))
                if count >= MIN_POINTS:
                    actual = float(np.median(zz))
                    break
            s.points.append(ControlPoint(n=n, local=(float(x), float(y), float(z)), design_z=float(z), actual_z=actual, count=count))
        slabs.append(s)
    return slabs


def build_pdf(project_name: str, model_label: str, scan_label: str, slabs: list[SlabScheme], tol_mm: float,
              to_coords, to_height, crs_label: str) -> bytes:
    """`to_coords(local xyz) -> (x, y)` in the project CRS, `to_height(local
    xyz) -> H` in the model's height system."""
    from reportlab.graphics.shapes import Circle, Drawing, Line, String
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from app.twin.report import _font

    font = _font()
    st = ParagraphStyle("b", fontName=font, fontSize=8.5, leading=11)
    h1 = ParagraphStyle("h1", fontName=font, fontSize=13, leading=17, spaceAfter=4)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
                            title="Исполнительная схема отметок")
    ok_c, warn_c, bad_c, none_c = colors.HexColor("#16A34A"), colors.HexColor("#D97706"), colors.HexColor("#DC2626"), colors.HexColor("#9CA3AF")

    def color(d_mm):
        if d_mm is None:
            return none_c
        return ok_c if abs(d_mm) <= tol_mm else (warn_c if abs(d_mm) <= 2 * tol_mm else bad_c)

    story = []
    for si, s in enumerate(slabs):
        if si:
            story.append(PageBreak())
        measured = [p for p in s.points if p.actual_z is not None]
        devs = [(p.actual_z - p.design_z) * 1000 for p in measured]
        within = sum(1 for d in devs if abs(d) <= tol_mm)
        story += [
            Paragraph(f"Исполнительная схема отметок верха: {s.name}", h1),
            Paragraph(f"Объект: {project_name} · этаж: {s.storey or '—'} · GlobalId {s.global_id}", st),
            Paragraph(f"Проект: {model_label} · факт: {scan_label} · сформирована {datetime.now():%d.%m.%Y %H:%M}", st),
            Paragraph(
                f"Точек: {len(s.points)}, измерено по скану: {len(measured)}"
                + (f" · в допуске ±{tol_mm:g} мм: {within} ({within / len(measured) * 100:.0f} %) · Δ от {min(devs):+.0f} до {max(devs):+.0f} мм" if devs else ""),
                st),
            Spacer(1, 4),
        ]
        # Plan
        W, H = 182 * mm, 120 * mm
        xy = np.array([e for seg in s.outline for e in seg]) if s.outline else np.array([p.local[:2] for p in s.points])
        lo, hi = xy.min(axis=0), xy.max(axis=0)
        k = min((W - 16 * mm) / max(hi[0] - lo[0], 1e-6), (H - 16 * mm) / max(hi[1] - lo[1], 1e-6))
        ox, oy = 8 * mm + (W - 16 * mm - (hi[0] - lo[0]) * k) / 2, 8 * mm + (H - 16 * mm - (hi[1] - lo[1]) * k) / 2

        def px(x, y):
            return ox + (x - lo[0]) * k, oy + (y - lo[1]) * k

        dr = Drawing(W, H)
        for (a, b) in s.outline:
            (x1, y1), (x2, y2) = px(*a), px(*b)
            dr.add(Line(x1, y1, x2, y2, strokeColor=colors.black, strokeWidth=0.8))
        fs = 6 if len(s.points) > 60 else 7
        for p in s.points:
            x, y = px(p.local[0], p.local[1])
            d = None if p.actual_z is None else (p.actual_z - p.design_z) * 1000
            dr.add(Circle(x, y, 1.6, fillColor=color(d), strokeColor=None))
            dr.add(String(x + 2.2, y + 1.5, str(p.n), fontName=font, fontSize=fs - 1, fillColor=colors.HexColor("#374151")))
            dr.add(String(x + 2.2, y - fs + 1, fmt_dev(d), fontName=font, fontSize=fs, fillColor=color(d)))
        # North arrow + scale
        dr.add(Line(W - 6 * mm, H - 14 * mm, W - 6 * mm, H - 6 * mm, strokeColor=colors.black, strokeWidth=0.8))
        dr.add(String(W - 7.2 * mm, H - 5 * mm, "С", fontName=font, fontSize=7))
        bar = 10.0 if (hi[0] - lo[0]) > 25 else 5.0
        dr.add(Line(8 * mm, 3 * mm, 8 * mm + bar * k, 3 * mm, strokeColor=colors.black, strokeWidth=1.2))
        dr.add(String(8 * mm + bar * k + 2, 2 * mm, f"{bar:g} м", fontName=font, fontSize=7))
        story += [dr, Paragraph(f"Подписи: номер точки и отклонение факт − проект, мм (зелёный — в допуске ±{tol_mm:g} мм, "
                                f"оранжевый — до ±{2 * tol_mm:g} мм, красный — больше, серый — нет точек скана).", st), Spacer(1, 4)]
        rows = [["№", f"X {crs_label}".strip(), f"Y {crs_label}".strip(), "H проект", "H факт", "Δ, мм", "Точек"]]
        for p in s.points:
            x, y = to_coords(p.local)
            hd = to_height(p.local)
            ha = None if p.actual_z is None else hd + (p.actual_z - p.design_z)
            rows.append([p.n, f"{x:.3f}", f"{y:.3f}", f"{hd:.3f}", "—" if ha is None else f"{ha:.3f}",
                         fmt_dev(None if p.actual_z is None else (p.actual_z - p.design_z) * 1000), p.count])
        t = Table(rows, colWidths=[10 * mm, 34 * mm, 34 * mm, 26 * mm, 26 * mm, 18 * mm, 16 * mm], repeatRows=1)
        style = [("FONTNAME", (0, 0), (-1, -1), font), ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                 ("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                 ("ALIGN", (1, 1), (-1, -1), "RIGHT")]
        for i, p in enumerate(s.points, start=1):
            d = None if p.actual_z is None else (p.actual_z - p.design_z) * 1000
            style.append(("TEXTCOLOR", (5, i), (5, i), color(d)))
        t.setStyle(TableStyle(style))
        story.append(t)
    if not slabs:
        story.append(Paragraph("Плиты для схемы не найдены (нужны элементы IfcSlab с горизонтальной верхней гранью).", st))
    doc.build(story)
    return buf.getvalue()
