"""Builders for small, real IFC / LAS / OBJ files used by the twin tests."""

from __future__ import annotations

import io

import numpy as np


def make_ifc(
    walls: list[tuple[str, float]] | None = None,
    map_conversion: dict | None = None,
    crs_name: str = "EPSG:32642",
    site_latlon: tuple[float, float] | None = None,
) -> bytes:
    """IFC4 with one storey and walls given as (name, x offset). Each wall gets a
    deterministic GlobalId derived from its name so versions can be compared."""
    import ifcopenshell
    import ifcopenshell.api.aggregate
    import ifcopenshell.api.context
    import ifcopenshell.api.geometry
    import ifcopenshell.api.georeference
    import ifcopenshell.api.project
    import ifcopenshell.api.pset
    import ifcopenshell.api.root
    import ifcopenshell.api.spatial
    import ifcopenshell.api.unit
    import ifcopenshell.guid

    walls = walls if walls is not None else [("Стена 1", 0.0), ("Стена 2", 6.0), ("Стена 3", 12.0)]
    m = ifcopenshell.api.project.create_file(version="IFC4")
    proj = ifcopenshell.api.root.create_entity(m, ifc_class="IfcProject", name="Test")
    ifcopenshell.api.unit.assign_unit(m)
    ctx = ifcopenshell.api.context.add_context(m, context_type="Model")
    body = ifcopenshell.api.context.add_context(
        m, context_type="Model", context_identifier="Body", target_view="MODEL_VIEW", parent=ctx
    )
    site = ifcopenshell.api.root.create_entity(m, ifc_class="IfcSite", name="Участок")
    if site_latlon:
        lat, lon = site_latlon
        site.RefLatitude = (int(lat), int((lat % 1) * 60), 0)
        site.RefLongitude = (int(lon), int((lon % 1) * 60), 0)
    bld = ifcopenshell.api.root.create_entity(m, ifc_class="IfcBuilding", name="Корпус 1")
    storey = ifcopenshell.api.root.create_entity(m, ifc_class="IfcBuildingStorey", name="Этаж 1")
    ifcopenshell.api.aggregate.assign_object(m, relating_object=proj, products=[site])
    ifcopenshell.api.aggregate.assign_object(m, relating_object=site, products=[bld])
    ifcopenshell.api.aggregate.assign_object(m, relating_object=bld, products=[storey])

    for name, x in walls:
        wall = ifcopenshell.api.root.create_entity(m, ifc_class="IfcWall", name=name)
        wall.GlobalId = ifcopenshell.guid.compress(
            __import__("uuid").uuid5(__import__("uuid").NAMESPACE_URL, name).hex
        )
        rep = ifcopenshell.api.geometry.add_wall_representation(m, context=body, length=5, height=3, thickness=0.2)
        ifcopenshell.api.geometry.assign_representation(m, product=wall, representation=rep)
        matrix = np.eye(4)
        matrix[0, 3] = x
        ifcopenshell.api.geometry.edit_object_placement(m, product=wall, matrix=matrix)
        ifcopenshell.api.spatial.assign_container(m, relating_structure=storey, products=[wall])
        pset = ifcopenshell.api.pset.add_pset(m, product=wall, name="Pset_WallCommon")
        ifcopenshell.api.pset.edit_pset(m, pset=pset, properties={"IsExternal": True, "FireRating": "REI60"})

    if map_conversion:
        ifcopenshell.api.georeference.add_georeferencing(m, name=crs_name)
        ifcopenshell.api.georeference.edit_georeferencing(m, coordinate_operation=map_conversion)

    return m.to_string().encode("utf-8")


def make_las(n: int = 50_000, epsg: int | None = 32642) -> bytes:
    import laspy
    import pyproj

    header = laspy.LasHeader(point_format=3, version="1.2")
    header.scales = [0.001, 0.001, 0.001]
    header.offsets = [500000, 5650000, 0]
    if epsg:
        header.add_crs(pyproj.CRS.from_epsg(epsg))
    las = laspy.LasData(header)
    rng = np.random.default_rng(1)
    x, y = rng.uniform(0, 100, n), rng.uniform(0, 80, n)
    las.x, las.y = 500000 + x, 5650000 + y
    las.z = 350 + np.sin(x / 10)
    las.red = (x / 100 * 65535).astype(np.uint16)
    las.green = (y / 80 * 65535).astype(np.uint16)
    las.blue = np.full(n, 20000, dtype=np.uint16)
    buf = io.BytesIO()
    las.write(buf)
    return buf.getvalue()


def make_obj() -> bytes:
    import trimesh

    box = trimesh.creation.box((10, 6, 3))
    box.apply_translation((0, 0, 1.5))
    return trimesh.exchange.obj.export_obj(box).encode()


def make_textured_terrain_glb(n: int = 60, size: float = 120.0) -> bytes:
    """Photogrammetry-like textured surface: n×n grid (2n² faces), one atlas
    image with a red-to-blue gradient across, glTF (Y-up)."""
    import numpy as np
    import trimesh
    from PIL import Image

    g = np.linspace(0, 1, n + 1)
    U, V = np.meshgrid(g, g)
    x, y = (U - 0.5) * size, (V - 0.5) * size
    z = 2.0 * np.sin(x / 15) * np.cos(y / 20)
    verts = np.column_stack([x.ravel(), z.ravel(), -y.ravel()])  # Y-up
    idx = np.arange((n + 1) ** 2).reshape(n + 1, n + 1)
    a, b, c, d = idx[:-1, :-1], idx[:-1, 1:], idx[1:, :-1], idx[1:, 1:]
    faces = np.vstack([np.column_stack([a.ravel(), b.ravel(), d.ravel()]), np.column_stack([a.ravel(), d.ravel(), c.ravel()])])
    img = np.zeros((512, 512, 3), np.uint8)
    img[..., 0] = np.linspace(255, 0, 512)[None, :]
    img[..., 2] = np.linspace(0, 255, 512)[None, :]
    mat = trimesh.visual.material.SimpleMaterial(image=Image.fromarray(img))
    uv = np.column_stack([U.ravel(), V.ravel()])
    mesh = trimesh.Trimesh(verts, faces, visual=trimesh.visual.TextureVisuals(uv=uv, material=mat), process=False)
    return mesh.export(file_type="glb")
