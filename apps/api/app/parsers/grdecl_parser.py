"""Eclipse/Petrel GRDECL ASCII grid parsing.

Supports:
  - SPECGRID for (nx, ny, nz).
  - COORD + ZCORN corner-point geometry, decoded into true per-cell corner
    coordinates (pillar interpolation), then approximated for rendering as
    an axis-aligned box per cell (centroid + bounding-box size) -- see
    docs/LIMITATIONS.md ("Corner-point grids").
  - Fallback to DX/DY/DZ/TOPS regular-grid geometry when COORD/ZCORN are
    absent.
  - ACTNUM for the active-cell mask (defaults to all-active if absent).
  - Property keywords PORO, PERMX, PERMY, PERMZ, SWAT/SW, SOIL/SO, NTG as
    per-active-cell float arrays.

Cell / property ordering: Eclipse's natural order, i fastest, then j, then k
-- both geometry and every property array are produced in this same order
before being filtered down to active cells, so indices line up exactly as
the API contract requires.
"""

from dataclasses import dataclass, field

import numpy as np

_PROPERTY_ALIASES = {
    "SW": "SWAT",
    "SO": "SOIL",
}
_KNOWN_KEYWORDS = {
    "SPECGRID",
    "COORD",
    "ZCORN",
    "ACTNUM",
    "DX",
    "DY",
    "DZ",
    "TOPS",
    "PORO",
    "PERMX",
    "PERMY",
    "PERMZ",
    "SWAT",
    "SW",
    "SOIL",
    "SO",
    "NTG",
}


@dataclass
class ParsedGrid:
    nx: int
    ny: int
    nz: int
    centers: np.ndarray  # (activeCount, 3)
    sizes: np.ndarray  # (activeCount, 3)
    active_mask: np.ndarray  # (nx*ny*nz,) bool, natural (i-fastest) order
    properties: dict[str, np.ndarray] = field(default_factory=dict)  # name -> (activeCount,)
    bounds: tuple[float, float, float, float, float, float] = (0, 0, 0, 0, 0, 0)


def _strip_comment(line: str) -> str:
    idx = line.find("--")
    return line[:idx] if idx >= 0 else line


def _expand_repeats(tokens: list[str]) -> list[str]:
    out: list[str] = []
    for tok in tokens:
        if "*" in tok and not tok.startswith("*") and not tok.endswith("*"):
            count_str, _, val = tok.partition("*")
            try:
                count = int(count_str)
            except ValueError:
                out.append(tok)
                continue
            out.extend([val] * count)
        else:
            out.append(tok)
    return out


def _read_keyword_blocks(text: str) -> dict[str, list[str]]:
    lines = [_strip_comment(line).strip() for line in text.splitlines()]
    result: dict[str, list[str]] = {}
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if not line:
            i += 1
            continue
        first_tok = line.split()[0].upper()
        if first_tok not in _KNOWN_KEYWORDS:
            i += 1
            continue
        kw = first_tok
        tokens: list[str] = line.split()[1:]
        i += 1
        terminated = False
        for t in tokens:
            if t == "/" or t.endswith("/"):
                terminated = True
        while not terminated and i < n:
            l2 = lines[i]
            i += 1
            for t in l2.split():
                if t == "/":
                    terminated = True
                    break
                tokens.append(t)
            if terminated:
                break
        cleaned = []
        for t in tokens:
            if t == "/":
                continue
            if t.endswith("/"):
                t = t[:-1]
                if t:
                    cleaned.append(t)
                continue
            cleaned.append(t)
        result[kw] = _expand_repeats(cleaned)
    return result


def _floats(tokens: list[str]) -> np.ndarray:
    vals = []
    for t in tokens:
        try:
            vals.append(float(t))
        except ValueError:
            continue
    return np.array(vals, dtype=float)


def parse_grdecl(raw: bytes) -> ParsedGrid:
    text = raw.decode("utf-8", errors="replace")
    blocks = _read_keyword_blocks(text)

    if "SPECGRID" not in blocks:
        raise ValueError("GRDECL file missing SPECGRID (nx ny nz)")
    specgrid_nums = _floats(blocks["SPECGRID"][:3])
    if len(specgrid_nums) < 3:
        raise ValueError("SPECGRID must specify nx, ny, nz")
    nx, ny, nz = (int(v) for v in specgrid_nums[:3])
    ncells = nx * ny * nz

    if "COORD" in blocks and "ZCORN" in blocks:
        cx, cy, cz, sx, sy, sz = _corner_point_geometry(nx, ny, nz, blocks["COORD"], blocks["ZCORN"])
    elif "DX" in blocks and "DY" in blocks and "DZ" in blocks:
        cx, cy, cz, sx, sy, sz = _regular_geometry(nx, ny, nz, blocks)
    else:
        raise ValueError("GRDECL file needs COORD+ZCORN or DX+DY+DZ(+TOPS) for cell geometry")

    if "ACTNUM" in blocks:
        actnum = _floats(blocks["ACTNUM"]).astype(int)
        if len(actnum) != ncells:
            raise ValueError(f"ACTNUM length {len(actnum)} != nx*ny*nz {ncells}")
        active_mask = actnum.astype(bool)
    else:
        active_mask = np.ones(ncells, dtype=bool)

    centers = np.column_stack([cx.reshape(-1), cy.reshape(-1), cz.reshape(-1)])[active_mask]
    sizes = np.column_stack([sx.reshape(-1), sy.reshape(-1), sz.reshape(-1)])[active_mask]

    properties: dict[str, np.ndarray] = {}
    for name in ("PORO", "PERMX", "PERMY", "PERMZ", "SWAT", "SW", "SOIL", "SO", "NTG"):
        if name in blocks:
            canonical = _PROPERTY_ALIASES.get(name, name)
            vals = _floats(blocks[name])
            if len(vals) != ncells:
                continue
            properties[canonical] = vals[active_mask]

    all_x = np.concatenate([centers[:, 0] - sizes[:, 0] / 2, centers[:, 0] + sizes[:, 0] / 2]) if len(centers) else np.array([0.0])
    all_y = np.concatenate([centers[:, 1] - sizes[:, 1] / 2, centers[:, 1] + sizes[:, 1] / 2]) if len(centers) else np.array([0.0])
    all_z = np.concatenate([centers[:, 2] - sizes[:, 2] / 2, centers[:, 2] + sizes[:, 2] / 2]) if len(centers) else np.array([0.0])
    bounds = (
        float(all_x.min()), float(all_y.min()), float(all_z.min()),
        float(all_x.max()), float(all_y.max()), float(all_z.max()),
    )

    return ParsedGrid(
        nx=nx, ny=ny, nz=nz,
        centers=centers, sizes=sizes, active_mask=active_mask,
        properties=properties, bounds=bounds,
    )


def _corner_point_geometry(nx: int, ny: int, nz: int, coord_tokens: list[str], zcorn_tokens: list[str]):
    coord = _floats(coord_tokens)
    zcorn = _floats(zcorn_tokens)

    expected_coord = (nx + 1) * (ny + 1) * 6
    if len(coord) != expected_coord:
        raise ValueError(f"COORD length {len(coord)} != expected {expected_coord}")
    expected_zcorn = 8 * nx * ny * nz
    if len(zcorn) != expected_zcorn:
        raise ValueError(f"ZCORN length {len(zcorn)} != expected {expected_zcorn}")

    coord_arr = coord.reshape(ny + 1, nx + 1, 6)
    top = coord_arr[:, :, 0:3]
    bot = coord_arr[:, :, 3:6]

    # zc[k, j, i, kk, jj, ii] -- Eclipse's natural ZCORN nesting (see module docstring).
    zc = zcorn.reshape(nz, 2, ny, 2, nx, 2).transpose(0, 2, 4, 1, 3, 5)

    xs = np.empty((nz, ny, nx, 2, 2, 2))
    ys = np.empty((nz, ny, nx, 2, 2, 2))
    zs = np.empty((nz, ny, nx, 2, 2, 2))

    for jj in (0, 1):
        for ii in (0, 1):
            top_c = top[jj : jj + ny, ii : ii + nx, :]  # (ny, nx, 3)
            bot_c = bot[jj : jj + ny, ii : ii + nx, :]
            x1, y1, z1 = top_c[..., 0], top_c[..., 1], top_c[..., 2]
            x2, y2, z2 = bot_c[..., 0], bot_c[..., 1], bot_c[..., 2]
            denom = z2 - z1
            safe_denom = np.where(denom == 0, 1.0, denom)
            for kk in (0, 1):
                zval = zc[:, :, :, kk, jj, ii]  # (nz, ny, nx)
                t = np.where(denom[None, :, :] == 0, 0.0, (zval - z1[None, :, :]) / safe_denom[None, :, :])
                xs[:, :, :, kk, jj, ii] = x1[None, :, :] + t * (x2 - x1)[None, :, :]
                ys[:, :, :, kk, jj, ii] = y1[None, :, :] + t * (y2 - y1)[None, :, :]
                zs[:, :, :, kk, jj, ii] = zval

    corners_flat_x = xs.reshape(nz, ny, nx, 8)
    corners_flat_y = ys.reshape(nz, ny, nx, 8)
    corners_flat_z = zs.reshape(nz, ny, nx, 8)

    cx = corners_flat_x.mean(axis=-1)
    cy = corners_flat_y.mean(axis=-1)
    cz = corners_flat_z.mean(axis=-1)
    sx = corners_flat_x.max(axis=-1) - corners_flat_x.min(axis=-1)
    sy = corners_flat_y.max(axis=-1) - corners_flat_y.min(axis=-1)
    sz = corners_flat_z.max(axis=-1) - corners_flat_z.min(axis=-1)

    return cx, cy, cz, sx, sy, sz


def _regular_geometry(nx: int, ny: int, nz: int, blocks: dict[str, list[str]]):
    ncells = nx * ny * nz
    dx = _floats(blocks["DX"])
    dy = _floats(blocks["DY"])
    dz = _floats(blocks["DZ"])
    if len(dx) == 1:
        dx = np.full(ncells, dx[0])
    if len(dy) == 1:
        dy = np.full(ncells, dy[0])
    if len(dz) == 1:
        dz = np.full(ncells, dz[0])
    if len(dx) != ncells or len(dy) != ncells or len(dz) != ncells:
        raise ValueError("DX/DY/DZ must each have nx*ny*nz values (or a single constant)")

    dx3 = dx.reshape(nz, ny, nx)
    dy3 = dy.reshape(nz, ny, nx)
    dz3 = dz.reshape(nz, ny, nx)

    if "TOPS" in blocks:
        tops = _floats(blocks["TOPS"])
        if len(tops) == nx * ny:
            top_col = tops.reshape(ny, nx)
            top3 = np.broadcast_to(top_col, (nz, ny, nx)).copy()
            # accumulate to per-layer top using column-representative dz (j,i fixed across k)
            cum = np.cumsum(dz3, axis=0)
            top3[1:, :, :] += cum[:-1, :, :]
        elif len(tops) == ncells:
            top3 = tops.reshape(nz, ny, nx)
        else:
            top3 = np.zeros((nz, ny, nx))
    else:
        top3 = np.zeros((nz, ny, nx))
        cum = np.cumsum(dz3, axis=0)
        top3[1:, :, :] = cum[:-1, :, :]

    cz = top3 + dz3 / 2.0

    x_widths = dx3[0, 0, :]
    x_edges = np.concatenate([[0.0], np.cumsum(x_widths)])
    x_center_1d = x_edges[:-1] + x_widths / 2.0

    y_widths = dy3[0, :, 0]
    y_edges = np.concatenate([[0.0], np.cumsum(y_widths)])
    y_center_1d = y_edges[:-1] + y_widths / 2.0

    cx = np.broadcast_to(x_center_1d[None, None, :], (nz, ny, nx)).copy()
    cy = np.broadcast_to(y_center_1d[None, :, None], (nz, ny, nx)).copy()

    return cx, cy, cz, dx3, dy3, dz3
