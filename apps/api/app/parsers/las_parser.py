"""LAS well-log parsing via `lasio`.

Pure function: bytes -> parsed structure. No DB/storage access here (see
docs/LIMITATIONS.md's note on background jobs being drop-in-replaceable with
Celery: parsers stay pure so the same function works from either).
"""

import io
from dataclasses import dataclass, field

import lasio
import numpy as np

# Mnemonics that, if present as curves, we treat as X/Y/TVD trajectory data
# embedded in the LAS file rather than as logs to plot.
_TRAJECTORY_MNEMONICS = {"x", "y", "tvd", "md", "incl", "inclination", "azim", "azimuth"}
_LOCATION_MNEMONICS_X = ["xwell", "x", "surfx", "sx", "long", "lon"]
_LOCATION_MNEMONICS_Y = ["ywell", "y", "surfy", "sy", "lati", "lat"]


@dataclass
class LasCurve:
    curve_name: str
    unit: str | None
    depths: np.ndarray
    values: np.ndarray


@dataclass
class LasTrajectoryPoint:
    md: float
    inclination: float | None
    azimuth: float | None
    tvd: float
    x: float
    y: float
    z: float


@dataclass
class ParsedLas:
    well_name: str
    surface_x: float | None
    surface_y: float | None
    kb_elevation: float | None
    total_depth: float | None
    curves: list[LasCurve] = field(default_factory=list)
    trajectory: list[LasTrajectoryPoint] | None = None


def _well_header_value(las: lasio.LASFile, *mnemonics: str) -> float | None:
    for m in mnemonics:
        try:
            item = las.well[m]
        except KeyError:
            continue
        val = item.value
        if val in (None, ""):
            continue
        try:
            return float(val)
        except (TypeError, ValueError):
            continue
    return None


def parse_las(raw: bytes) -> ParsedLas:
    text = raw.decode("utf-8", errors="replace")
    las = lasio.read(io.StringIO(text))

    well_name = None
    try:
        well_name = (las.well["WELL"].value or "").strip() or None
    except KeyError:
        pass

    surface_x = _well_header_value(las, *_LOCATION_MNEMONICS_X)
    surface_y = _well_header_value(las, *_LOCATION_MNEMONICS_Y)
    kb_elevation = _well_header_value(las, "EKB", "KB", "EGL")
    total_depth = _well_header_value(las, "STOP", "TD")
    if total_depth is None and las.index is not None and len(las.index):
        total_depth = float(np.nanmax(las.index))

    depth_mnemonic = (las.curves[0].mnemonic if las.curves else "DEPT").lower()
    depths = np.asarray(las.index, dtype=float)

    curves: list[LasCurve] = []
    by_mnemonic: dict[str, np.ndarray] = {}
    for curve in las.curves:
        mnem = curve.mnemonic
        if mnem.lower() == depth_mnemonic:
            continue
        values = np.asarray(curve.data, dtype=float)
        by_mnemonic[mnem.lower()] = values
        if mnem.lower() in _TRAJECTORY_MNEMONICS:
            # Still expose it as a plottable curve too -- LAS files that
            # embed deviation data as curves are otherwise ordinary logs.
            pass
        curves.append(LasCurve(curve_name=mnem, unit=curve.unit or None, depths=depths, values=values))

    trajectory: list[LasTrajectoryPoint] | None = None
    has_xytvd = all(k in by_mnemonic for k in ("x", "y", "tvd"))
    has_mdinclazim = all(k in by_mnemonic for k in ("md", "incl", "azim")) or all(
        k in by_mnemonic for k in ("md", "inclination", "azimuth")
    )

    if has_xytvd:
        x_arr, y_arr, tvd_arr = by_mnemonic["x"], by_mnemonic["y"], by_mnemonic["tvd"]
        md_arr = by_mnemonic.get("md", depths)
        incl_arr = by_mnemonic.get("incl") or by_mnemonic.get("inclination")
        azim_arr = by_mnemonic.get("azim") or by_mnemonic.get("azimuth")
        z0 = kb_elevation if kb_elevation is not None else 0.0
        trajectory = []
        for idx in range(len(md_arr)):
            tvd = float(tvd_arr[idx])
            if np.isnan(tvd):
                continue
            trajectory.append(
                LasTrajectoryPoint(
                    md=float(md_arr[idx]),
                    inclination=float(incl_arr[idx]) if incl_arr is not None and not np.isnan(incl_arr[idx]) else None,
                    azimuth=float(azim_arr[idx]) if azim_arr is not None and not np.isnan(azim_arr[idx]) else None,
                    tvd=tvd,
                    x=float(x_arr[idx]),
                    y=float(y_arr[idx]),
                    z=z0 - tvd,
                )
            )
    elif has_mdinclazim:
        from app.parsers.trajectory_csv_parser import minimum_curvature

        md_arr = by_mnemonic["md"]
        incl_arr = by_mnemonic.get("incl") or by_mnemonic.get("inclination")
        azim_arr = by_mnemonic.get("azim") or by_mnemonic.get("azimuth")
        origin_x = surface_x or 0.0
        origin_y = surface_y or 0.0
        origin_z = kb_elevation if kb_elevation is not None else 0.0
        computed = minimum_curvature(md_arr, incl_arr, azim_arr, origin_x, origin_y, origin_z)
        trajectory = [
            LasTrajectoryPoint(
                md=float(row[0]),
                inclination=float(row[1]),
                azimuth=float(row[2]),
                tvd=float(row[3]),
                x=float(row[4]),
                y=float(row[5]),
                z=float(row[6]),
            )
            for row in computed
        ]

    return ParsedLas(
        well_name=well_name or "UNKNOWN",
        surface_x=surface_x,
        surface_y=surface_y,
        kb_elevation=kb_elevation,
        total_depth=total_depth,
        curves=curves,
        trajectory=trajectory,
    )
