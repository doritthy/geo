"""Well trajectory parsing from CSV/TXT files.

Two supported shapes (per docs/API_CONTRACT.md's `column_mapping`):
  1. MD, Inclination, Azimuth  -> TVD/X/Y/Z computed via the minimum
     curvature method (implemented here with numpy, no external survey lib).
  2. X, Y, TVD given directly.

`column_mapping` (optional): {"md":"MD","incl":"Incl","azim":"Azim","x":"X","y":"Y","tvd":"TVD"}
maps our canonical field names to the CSV's actual header names.
"""

from dataclasses import dataclass

import numpy as np

_DEFAULT_ALIASES: dict[str, list[str]] = {
    "md": ["md", "measured_depth", "depth", "meas_depth"],
    "incl": ["incl", "inclination", "inc", "angle"],
    "azim": ["azim", "azimuth", "az", "brg", "bearing"],
    "x": ["x", "east", "easting"],
    "y": ["y", "north", "northing"],
    "tvd": ["tvd", "true_vertical_depth", "tvdss"],
}


@dataclass
class TrajectoryRow:
    md: float
    inclination: float | None
    azimuth: float | None
    tvd: float
    x: float
    y: float
    z: float


def minimum_curvature(
    md: np.ndarray,
    incl_deg: np.ndarray,
    azim_deg: np.ndarray,
    origin_x: float,
    origin_y: float,
    origin_z: float,
) -> np.ndarray:
    """Minimum-curvature survey calculation.

    Returns an (n, 7) array of [md, incl, azim, tvd, x, y, z].
    `origin_z` is the KB/surface elevation; z = origin_z - tvd.
    """
    md = np.asarray(md, dtype=float)
    incl = np.radians(np.asarray(incl_deg, dtype=float))
    azim = np.radians(np.asarray(azim_deg, dtype=float))
    n = len(md)

    tvd = np.zeros(n)
    north = np.zeros(n)
    east = np.zeros(n)

    for i in range(1, n):
        dmd = md[i] - md[i - 1]
        i1, i2 = incl[i - 1], incl[i]
        a1, a2 = azim[i - 1], azim[i]

        cos_beta = np.cos(i2 - i1) - np.sin(i1) * np.sin(i2) * (1 - np.cos(a2 - a1))
        cos_beta = np.clip(cos_beta, -1.0, 1.0)
        beta = np.arccos(cos_beta)
        rf = 1.0 if beta < 1e-9 else (2.0 / beta) * np.tan(beta / 2.0)

        d_north = dmd / 2.0 * (np.sin(i1) * np.cos(a1) + np.sin(i2) * np.cos(a2)) * rf
        d_east = dmd / 2.0 * (np.sin(i1) * np.sin(a1) + np.sin(i2) * np.sin(a2)) * rf
        d_tvd = dmd / 2.0 * (np.cos(i1) + np.cos(i2)) * rf

        north[i] = north[i - 1] + d_north
        east[i] = east[i - 1] + d_east
        tvd[i] = tvd[i - 1] + d_tvd

    x = origin_x + east
    y = origin_y + north
    z = origin_z - tvd

    return np.column_stack([md, np.degrees(incl), np.degrees(azim), tvd, x, y, z])


def _sniff_rows(text: str) -> tuple[list[str], list[list[str]]]:
    lines = [line for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]
    if not lines:
        raise ValueError("Empty CSV/trajectory file")
    header_line = lines[0]
    if "," in header_line:
        delim = ","
    elif "\t" in header_line:
        delim = "\t"
    else:
        delim = None

    if delim:
        headers = [h.strip() for h in header_line.split(delim)]
        rows = [[c.strip() for c in line.split(delim)] for line in lines[1:]]
    else:
        headers = header_line.split()
        rows = [line.split() for line in lines[1:]]
    return headers, rows


def _resolve_column(field: str, headers_lower: list[str], mapping: dict | None) -> int | None:
    candidates: list[str] = []
    if mapping and field in mapping and mapping[field]:
        candidates.append(str(mapping[field]))
    candidates.extend(_DEFAULT_ALIASES[field])
    for cand in candidates:
        cl = cand.strip().lower()
        if cl in headers_lower:
            return headers_lower.index(cl)
    return None


def parse_csv_trajectory(raw: bytes, column_mapping: dict | None, kb_elevation: float = 0.0) -> list[TrajectoryRow]:
    text = raw.decode("utf-8", errors="replace")
    headers, rows = _sniff_rows(text)
    headers_lower = [h.lower() for h in headers]

    idx = {field: _resolve_column(field, headers_lower, column_mapping) for field in _DEFAULT_ALIASES}

    def col(row: list[str], i: int | None) -> float | None:
        if i is None or i >= len(row) or row[i] == "":
            return None
        try:
            return float(row[i])
        except ValueError:
            return None

    has_xytvd = idx["x"] is not None and idx["y"] is not None and idx["tvd"] is not None
    has_mdinclazim = idx["md"] is not None and idx["incl"] is not None and idx["azim"] is not None

    if not has_xytvd and not has_mdinclazim:
        raise ValueError(
            "CSV trajectory needs either X/Y/TVD columns or MD/Inclination/Azimuth columns "
            "(use column_mapping to map non-standard headers)"
        )

    clean_rows = [r for r in rows if any(c.strip() for c in r)]

    if has_mdinclazim:
        md_vals, incl_vals, azim_vals = [], [], []
        for r in clean_rows:
            md_v, incl_v, azim_v = col(r, idx["md"]), col(r, idx["incl"]), col(r, idx["azim"])
            if md_v is None or incl_v is None or azim_v is None:
                continue
            md_vals.append(md_v)
            incl_vals.append(incl_v)
            azim_vals.append(azim_v)
        computed = minimum_curvature(
            np.array(md_vals), np.array(incl_vals), np.array(azim_vals), 0.0, 0.0, kb_elevation
        )
        return [
            TrajectoryRow(md=r[0], inclination=r[1], azimuth=r[2], tvd=r[3], x=r[4], y=r[5], z=r[6])
            for r in computed
        ]

    # Direct X/Y/TVD.
    result: list[TrajectoryRow] = []
    for r in clean_rows:
        x_v, y_v, tvd_v = col(r, idx["x"]), col(r, idx["y"]), col(r, idx["tvd"])
        if x_v is None or y_v is None or tvd_v is None:
            continue
        md_v = col(r, idx["md"])
        if md_v is None:
            # No MD column supplied alongside direct X/Y/TVD: approximate MD
            # as TVD (vertical-well assumption) since `md` is NOT NULL in
            # the schema. Documented in docs/LIMITATIONS.md.
            md_v = tvd_v
        incl_v = col(r, idx["incl"])
        azim_v = col(r, idx["azim"])
        result.append(
            TrajectoryRow(
                md=md_v,
                inclination=incl_v,
                azimuth=azim_v,
                tvd=tvd_v,
                x=x_v,
                y=y_v,
                z=kb_elevation - tvd_v,
            )
        )
    return result
