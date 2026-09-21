"""Direct unit tests for the lower-priority parsers (xyz, surfer_grd, mesh)
and the minimum-curvature math, exercised directly against the pure parser
functions (no DB/HTTP needed for these).
"""

import numpy as np

from app.parsers.surfer_grd_parser import parse_surfer_grd
from app.parsers.trajectory_csv_parser import minimum_curvature
from app.parsers.xyz_parser import parse_xyz


def test_minimum_curvature_vertical_well_matches_md():
    md = np.array([0, 100, 200, 300])
    incl = np.array([0, 0, 0, 0])
    azim = np.array([0, 0, 0, 0])
    result = minimum_curvature(md, incl, azim, origin_x=1000.0, origin_y=2000.0, origin_z=50.0)
    tvd = result[:, 3]
    x = result[:, 4]
    y = result[:, 5]
    z = result[:, 6]
    assert np.allclose(tvd, md)  # purely vertical: TVD == MD
    assert np.allclose(x, 1000.0)
    assert np.allclose(y, 2000.0)
    assert np.allclose(z, 50.0 - md)


def test_surfer_grd_parser_roundtrip():
    text = (
        "DSAA\n"
        "3 2\n"
        "0 20\n"
        "0 10\n"
        "1 6\n"
        "1 2 3 4 5 6\n"
    )
    parsed = parse_surfer_grd(text.encode("utf-8"))
    assert parsed.cols == 3
    assert parsed.rows == 2
    assert parsed.origin_x == 0
    assert parsed.origin_y == 0
    assert parsed.cell_size_x == 10.0
    assert parsed.cell_size_y == 10.0
    assert list(parsed.heights) == [1, 2, 3, 4, 5, 6]
    assert parsed.min_z == 1.0
    assert parsed.max_z == 6.0


def test_xyz_parser_grids_scatter_points():
    lines = []
    for x in range(5):
        for y in range(5):
            lines.append(f"{x} {y} {x + y}")
    raw = "\n".join(lines).encode("utf-8")
    parsed = parse_xyz(raw, target_dim=200)
    assert parsed.cols >= 2 and parsed.rows >= 2
    finite = parsed.heights[np.isfinite(parsed.heights)]
    assert finite.size == parsed.cols * parsed.rows
    # z = x + y over [0,4]x[0,4] -> min 0, max 8, roughly preserved by interpolation.
    assert -0.5 <= parsed.min_z <= 0.5
    assert 7.5 <= parsed.max_z <= 8.5


def test_mesh_parser_obj():
    from app.parsers.mesh_parser import parse_mesh

    obj_text = (
        "v 0 0 0\n"
        "v 1 0 0\n"
        "v 0 1 0\n"
        "f 1 2 3\n"
    )
    parsed = parse_mesh(obj_text.encode("utf-8"), "obj")
    assert parsed.vertex_count == 3
    assert parsed.face_count == 1
    assert parsed.bounds_min == [0.0, 0.0, 0.0]
    assert parsed.bounds_max == [1.0, 1.0, 0.0]
