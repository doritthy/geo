"""PDF report of a deviation analysis (ReportLab): summary, legend and
histogram, plan-view deviation map image, worst elements with coordinates
in the project CRS."""

from __future__ import annotations

import io
import os
from datetime import datetime

import numpy as np
from PIL import Image, ImageDraw
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image as RLImage
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.twin import deviation as dev

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
]


def _font() -> str:
    """Cyrillic-capable font (fonts-dejavu-core in the API image)."""
    if "DejaVu" in pdfmetrics.getRegisteredFontNames():
        return "DejaVu"
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            pdfmetrics.registerFont(TTFont("DejaVu", path))
            return "DejaVu"
    return "Helvetica"


def plan_image(xy: np.ndarray, bins: np.ndarray, size: int = 1400) -> bytes:
    lut = [c for _, c in dev.bin_colors()]
    img = Image.new("RGB", (size, size), (255, 255, 255))
    if len(xy) == 0:
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue()
    lo, hi = xy.min(axis=0), xy.max(axis=0)
    span = float(max(hi - lo)) or 1.0
    pad = 30
    scale = (size - 2 * pad) / span
    px = ((xy - lo) * scale + pad).astype(int)
    px[:, 1] = size - px[:, 1]
    draw = ImageDraw.Draw(img)
    r = max(1, int(round(scale * 0.06)))  # ~6 cm footprint per point
    # Unrelated points first (light), then in tolerance, outliers on top.
    order = np.lexsort((np.abs(bins - 3), bins >= 0))
    for i in order:
        b = bins[i]
        c = (225, 225, 225) if b < 0 else lut[b]
        x, y = px[i]
        draw.rectangle((x - r, y - r, x + r, y + r), fill=c)
    # scale bar 10 m
    bar = 10 * scale
    draw.line((pad, size - 15, pad + bar, size - 15), fill=(0, 0, 0), width=3)
    draw.text((pad, size - 30), "10 м", fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def build_pdf(project_name: str, result: dict, plan_png: bytes | None, crs_forward=None, crs_label: str = "") -> bytes:
    font = _font()
    st = ParagraphStyle("b", fontName=font, fontSize=9, leading=12)
    h1 = ParagraphStyle("h1", fontName=font, fontSize=15, leading=19, spaceAfter=6)
    h2 = ParagraphStyle("h2", fontName=font, fontSize=11, leading=14, spaceBefore=8, spaceAfter=4)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm,
                            title="Отчёт об отклонениях")
    hist = result["histogram"]
    tol = result["tolerances"]
    story = [
        Paragraph("Отчёт об отклонениях «факт — проект»", h1),
        Paragraph(f"Проект: {project_name}", st),
        Paragraph(f"Съёмка: {result['cloud']['name']} {result['cloud'].get('captured_at') or ''}", st),
        Paragraph(f"Модель: {result['bim']['name']} (версия {result['bim']['version']})", st),
        Paragraph(f"Сформирован: {datetime.now().strftime('%d.%m.%Y %H:%M')}", st),
        Paragraph(
            f"Допуски: ±{tol[0]*100:g} / ±{tol[1]*100:g} / ±{tol[2]*100:g} см · точек в анализе: "
            f"{result['points_used']:,} из {result['points_total']:,} · радиус привязки к модели {result['max_distance']*100:g} см".replace(",", " "),
            st,
        ),
        Spacer(1, 6),
        Paragraph("Сводка", h2),
    ]
    summary = [
        ["Точек, относящихся к модели", f"{hist['related_points']:,}".replace(",", " ")],
        ["Вне модели (рельеф, леса и пр.)", f"{hist['unrelated_points']:,}".replace(",", " ")],
        [f"В допуске ±{tol[1]*100:g} см", f"{hist['within_tolerance']*100:.1f} %"],
        ["Среднее отклонение", f"{(hist['mean'] or 0)*1000:.1f} мм"],
        ["СКО (RMS)", f"{(hist['rms'] or 0)*1000:.1f} мм"],
        ["95-й процентиль |d|", f"{(hist['p95_abs'] or 0)*1000:.1f} мм"],
    ]
    t = Table(summary, colWidths=[90 * mm, 60 * mm])
    t.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), font), ("FONTSIZE", (0, 0), (-1, -1), 9),
                           ("GRID", (0, 0), (-1, -1), 0.3, colors.grey)]))
    story += [t, Paragraph("Распределение отклонений", h2)]
    total = max(hist["related_points"], 1)
    rows = [["Диапазон", "Точек", "%"]]
    for b in hist["bins"]:
        rows.append([b["label"], f"{b['count']:,}".replace(",", " "), f"{b['count'] / total * 100:.1f}"])
    t = Table(rows, colWidths=[50 * mm, 40 * mm, 25 * mm])
    style = [("FONTNAME", (0, 0), (-1, -1), font), ("FONTSIZE", (0, 0), (-1, -1), 9),
             ("GRID", (0, 0), (-1, -1), 0.3, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey)]
    for i, b in enumerate(hist["bins"], start=1):
        style.append(("BACKGROUND", (0, i), (0, i), colors.HexColor(b["color"])))
    t.setStyle(TableStyle(style))
    story.append(t)

    if plan_png:
        story += [Paragraph("Карта отклонений (план)", h2), RLImage(io.BytesIO(plan_png), width=170 * mm, height=170 * mm)]

    story.append(Paragraph("Элементы с наибольшими отклонениями", h2))
    head = ["Элемент", "Класс", "Точек", "Ср., мм", "95%, мм", "Макс., мм", f"Координаты {crs_label}".strip()]
    rows = [head]
    significant = [e for e in result["elements"] if e["points"] >= 20]
    for e in significant[:40]:
        if crs_forward:
            x, y = crs_forward(e["longitude"], e["latitude"])
            coord = f"{x:.2f}; {y:.2f}; H {e['height']:.2f}"
        else:
            coord = f"{e['latitude']:.6f}; {e['longitude']:.6f}; H {e['height']:.2f}"
        rows.append([
            Paragraph((e.get("name") or e["global_id"])[:40], st), e["ifc_type"].replace("Ifc", ""), e["points"],
            f"{e['mean']*1000:.1f}", f"{e['p95_abs']*1000:.1f}", f"{e['max_abs']*1000:.1f}", Paragraph(coord, st),
        ])
    t = Table(rows, colWidths=[40 * mm, 18 * mm, 13 * mm, 15 * mm, 15 * mm, 16 * mm, 53 * mm], repeatRows=1)
    t.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), font), ("FONTSIZE", (0, 0), (-1, -1), 8),
                           ("GRID", (0, 0), (-1, -1), 0.3, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                           ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(t)
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "Знак: «+» — фактическая поверхность снаружи проектной (наплыв, выступ), «−» — внутри (недобор, прогиб). "
        "Высоты эллипсоидальные с учётом поправки, заданной при загрузке.", st))
    doc.build(story)
    return buf.getvalue()
