"""Generate a small, georeferenced demo dataset for the construction twin:

* demo_building_v1.ifc / demo_building_v2.ifc -- 5-storey frame building
  (slabs, columns, walls, windows) with IfcMapConversion in WGS 84 / UTM 42N
  (EPSG:32642), ~69°E 51°N (Kazakhstan). v2 changes a few elements (for version compare).
* demo_scan.laz -- "as-built" point cloud of the lower 3 storeys (surfaces of
  slabs and walls, with noise) plus terrain, in EPSG:32642.
* demo_site.geojson -- site boundary polygon in EPSG:32642.

Usage:  python scripts/make_demo_data.py <output dir>
"""

from __future__ import annotations

import json
import os
import sys
import uuid

import numpy as np

E0, N0, H0 = 499_850.0, 5_665_700.0, 347.0  # site origin in EPSG:32642 (≈ 69.0°E, 51.13°N)
BAYS_X, BAYS_Y, SPAN, STOREY_H = 6, 3, 6.0, 3.3


def _guid(name: str) -> str:
    import ifcopenshell.guid

    return ifcopenshell.guid.compress(uuid.uuid5(uuid.NAMESPACE_URL, f"demo/{name}").hex)


def make_building(storeys: int = 5, variant: int = 1) -> bytes:
    import ifcopenshell.api.aggregate
    import ifcopenshell.api.context
    import ifcopenshell.api.geometry
    import ifcopenshell.api.georeference
    import ifcopenshell.api.profile
    import ifcopenshell.api.project
    import ifcopenshell.api.pset
    import ifcopenshell.api.root
    import ifcopenshell.api.spatial
    import ifcopenshell.api.style
    import ifcopenshell.api.unit

    m = ifcopenshell.api.project.create_file(version="IFC4")
    proj = ifcopenshell.api.root.create_entity(m, ifc_class="IfcProject", name="ЖК Демо")
    ifcopenshell.api.unit.assign_unit(m)
    ctx = ifcopenshell.api.context.add_context(m, context_type="Model")
    body = ifcopenshell.api.context.add_context(
        m, context_type="Model", context_identifier="Body", target_view="MODEL_VIEW", parent=ctx
    )
    site = ifcopenshell.api.root.create_entity(m, ifc_class="IfcSite", name="Участок")
    bld = ifcopenshell.api.root.create_entity(m, ifc_class="IfcBuilding", name="Корпус А")
    ifcopenshell.api.aggregate.assign_object(m, relating_object=proj, products=[site])
    ifcopenshell.api.aggregate.assign_object(m, relating_object=site, products=[bld])

    ifcopenshell.api.georeference.add_georeferencing(m, name="EPSG:32642")
    ifcopenshell.api.georeference.edit_georeferencing(
        m, coordinate_operation={"Eastings": E0, "Northings": N0, "OrthogonalHeight": H0}
    )

    def styled(rgb, transparency=0.0):
        style = ifcopenshell.api.style.add_style(m)
        ifcopenshell.api.style.add_surface_style(
            m, style=style, ifc_class="IfcSurfaceStyleShading",
            attributes={"SurfaceColour": {"Name": None, "Red": rgb[0], "Green": rgb[1], "Blue": rgb[2]},
                        "Transparency": transparency},
        )
        return style

    concrete = styled((0.72, 0.72, 0.74))
    brick = styled((0.80, 0.55, 0.42))
    glass = styled((0.55, 0.75, 0.92), 0.55)

    col_profile = ifcopenshell.api.profile.add_parameterized_profile(m, ifc_class="IfcRectangleProfileDef")
    col_profile.ProfileType = "AREA"
    col_profile.XDim, col_profile.YDim = 0.4, 0.4

    lx, ly = BAYS_X * SPAN, BAYS_Y * SPAN

    def place(product, x, y, z, rot=0.0):
        c, s = np.cos(rot), np.sin(rot)
        mat = np.array([[c, -s, 0, x], [s, c, 0, y], [0, 0, 1, z], [0, 0, 0, 1]], dtype=float)
        ifcopenshell.api.geometry.edit_object_placement(m, product=product, matrix=mat)

    def add(ifc_class, name, rep, style, storey, x, y, z, rot=0.0, psets=None):
        el = ifcopenshell.api.root.create_entity(m, ifc_class=ifc_class, name=name)
        el.GlobalId = _guid(name)
        ifcopenshell.api.geometry.assign_representation(m, product=el, representation=rep)
        ifcopenshell.api.style.assign_representation_styles(m, shape_representation=rep, styles=[style])
        place(el, x, y, z, rot)
        ifcopenshell.api.spatial.assign_container(m, relating_structure=storey, products=[el])
        for pset_name, props in (psets or {}).items():
            pset = ifcopenshell.api.pset.add_pset(m, product=el, name=pset_name)
            ifcopenshell.api.pset.edit_pset(m, pset=pset, properties=props)
        return el

    for k in range(storeys):
        z = k * STOREY_H
        storey = ifcopenshell.api.root.create_entity(m, ifc_class="IfcBuildingStorey", name=f"Этаж {k + 1}")
        storey.Elevation = z
        ifcopenshell.api.aggregate.assign_object(m, relating_object=bld, products=[storey])

        slab_rep = ifcopenshell.api.geometry.add_slab_representation(
            m, context=body, depth=0.22, polyline=[(0, 0), (lx, 0), (lx, ly), (0, ly), (0, 0)]
        )
        add("IfcSlab", f"Плита перекрытия {k + 1}", slab_rep, concrete, storey, 0, 0, z,
            psets={"Pset_SlabCommon": {"LoadBearing": True, "FireRating": "REI90"},
                   "Qto_SlabBaseQuantities": {"NetVolume": round(lx * ly * 0.22, 2)}})

        for i in range(BAYS_X + 1):
            for j in range(BAYS_Y + 1):
                h = STOREY_H - 0.22
                # v2: column C-3-1 on storey 2 moved by 15 cm (geometry change)
                dx = 0.15 if (variant == 2 and k == 1 and i == 3 and j == 1) else 0.0
                rep = ifcopenshell.api.geometry.add_profile_representation(m, context=body, profile=col_profile, depth=h)
                # Perimeter columns sit inside the 0.3 m external walls.
                cx = min(max(i * SPAN, 0.5), lx - 0.5) + dx
                cy = min(max(j * SPAN, 0.5), ly - 0.5)
                add("IfcColumn", f"Колонна {k + 1}-{i}-{j}", rep, concrete, storey, cx, cy, z + 0.22,
                    psets={"Pset_ColumnCommon": {"LoadBearing": True, "Reference": "К-1"}})

        for side, (x, y, rot, length) in enumerate(
            [(0, 0, 0.0, lx), (lx, 0, np.pi / 2, ly), (lx, ly, np.pi, lx), (0, ly, -np.pi / 2, ly)]
        ):
            if variant == 2 and k == storeys - 1 and side == 2:
                continue  # v2: north wall of the top floor removed
            rep = ifcopenshell.api.geometry.add_wall_representation(
                m, context=body, length=length, height=STOREY_H - 0.22, thickness=0.3
            )
            fire = "REI150" if (variant == 2 and side == 0) else "REI120"  # v2: property change
            add("IfcWall", f"Наружная стена {k + 1}-{side}", rep, brick, storey, x, y, z + 0.22, rot,
                psets={"Pset_WallCommon": {"IsExternal": True, "FireRating": fire}})
            for w in range(int(length // SPAN)):
                wrep = ifcopenshell.api.geometry.add_wall_representation(
                    m, context=body, length=2.0, height=1.5, thickness=0.05
                )
                c, s = np.cos(rot), np.sin(rot)
                off = w * SPAN + 2.0
                add("IfcWindow", f"Окно {k + 1}-{side}-{w}", wrep, glass, storey,
                    x + c * off - s * -0.05, y + s * off + c * -0.05, z + 1.1, rot,
                    psets={"Pset_WindowCommon": {"IsExternal": True, "ThermalTransmittance": 1.1}})
        if variant == 2 and k == storeys - 1:
            rep = ifcopenshell.api.geometry.add_wall_representation(m, context=body, length=lx, height=1.2, thickness=0.25)
            add("IfcRailing", "Парапет кровли", rep, concrete, storey, lx, ly, z + STOREY_H, np.pi)

    return m.to_string().encode("utf-8")


def make_scan(storeys_built: int = 3, spacing: float = 0.12, seed: int = 7) -> bytes:
    """Points sampled on built slabs/walls (+2 cm noise, one slab sagging 4 cm)
    and on surrounding terrain, in EPSG:32642."""
    import io

    import laspy
    import pyproj

    rng = np.random.default_rng(seed)
    lx, ly = BAYS_X * SPAN, BAYS_Y * SPAN
    pts, cols = [], []

    def grid(x0, x1, y0, y1, step):
        xs = np.arange(x0, x1, step)
        ys = np.arange(y0, y1, step)
        gx, gy = np.meshgrid(xs, ys)
        return gx.ravel(), gy.ravel()

    # terrain
    gx, gy = grid(-25, lx + 25, -25, ly + 25, spacing * 3)
    outside = ~((gx > -0.5) & (gx < lx + 0.5) & (gy > -0.5) & (gy < ly + 0.5))
    gx, gy = gx[outside], gy[outside]
    gz = -0.05 + 0.02 * np.sin(gx / 7) + rng.normal(0, 0.02, gx.size)
    pts.append(np.column_stack([gx, gy, gz]))
    cols.append(np.tile([150, 130, 100], (gx.size, 1)))

    for k in range(storeys_built + 1):
        z = k * STOREY_H + 0.22
        sx, sy = grid(0, lx, 0, ly, spacing)
        sag = 0.04 * np.exp(-(((sx - lx / 2) / 8) ** 2 + ((sy - ly / 2) / 5) ** 2)) if k == 2 else 0
        sz = z - sag + rng.normal(0, 0.01, sx.size)
        if k < storeys_built:  # top slab surface only on finished floors
            pts.append(np.column_stack([sx, sy, sz]))
            cols.append(np.tile([185, 185, 190], (sx.size, 1)))
        if k == storeys_built:
            break
        for x0, y0, x1, y1 in [(0, 0, lx, 0), (lx, 0, lx, ly), (lx, ly, 0, ly), (0, ly, 0, 0)]:
            length = np.hypot(x1 - x0, y1 - y0)
            t = np.arange(0, length, spacing)
            hz = np.arange(0, STOREY_H - 0.22, spacing)
            tt, hh = np.meshgrid(t, hz)
            tt, hh = tt.ravel(), hh.ravel()
            ux, uy = (x1 - x0) / length, (y1 - y0) / length
            # Outer wall face: the IFC walls extend inward from their axis line.
            wx = x0 + ux * tt
            wy = y0 + uy * tt
            pts.append(np.column_stack([wx, wy, z + hh + rng.normal(0, 0.01, tt.size)]))
            cols.append(np.tile([200, 140, 110], (tt.size, 1)))

    xyz = np.vstack(pts)
    rgb = np.vstack(cols).astype(np.uint16) * 256
    header = laspy.LasHeader(point_format=3, version="1.2")
    header.scales = [0.001, 0.001, 0.001]
    header.offsets = [E0, N0, H0]
    header.add_crs(pyproj.CRS.from_epsg(32642))
    las = laspy.LasData(header)
    las.x, las.y, las.z = xyz[:, 0] + E0, xyz[:, 1] + N0, xyz[:, 2] + H0
    las.red, las.green, las.blue = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    buf = io.BytesIO()
    las.write(buf, do_compress=True)
    return buf.getvalue()


def make_site_geojson() -> bytes:
    lx, ly = BAYS_X * SPAN, BAYS_Y * SPAN
    ring = [[E0 - 20, N0 - 20], [E0 + lx + 20, N0 - 20], [E0 + lx + 20, N0 + ly + 20], [E0 - 20, N0 + ly + 20], [E0 - 20, N0 - 20]]
    gj = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::32642"}},
        "features": [
            {"type": "Feature", "properties": {"Название": "Граница участка", "Кадастровый номер": "21-320-001-123"},
             "geometry": {"type": "Polygon", "coordinates": [ring]}}
        ],
    }
    return json.dumps(gj, ensure_ascii=False).encode()


def main(out: str) -> None:
    os.makedirs(out, exist_ok=True)
    for name, data in [
        ("demo_building_v1.ifc", make_building(variant=1)),
        ("demo_building_v2.ifc", make_building(variant=2)),
        ("demo_scan.laz", make_scan()),
        ("demo_site.geojson", make_site_geojson()),
    ]:
        with open(os.path.join(out, name), "wb") as fh:
            fh.write(data)
        print(f"{name}: {len(data) / 1e6:.2f} MB")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "demo_data")
