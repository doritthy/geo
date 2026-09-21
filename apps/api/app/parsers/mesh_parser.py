"""OBJ/PLY/STL mesh ingestion via `trimesh`.

Per the task brief, full 3D mesh-grid rendering is out of scope for this
pass -- we load the mesh, validate it parses, and store basic stats into
`files.metadata` (vertex/face counts and bounding box) so the frontend can
at least show something meaningful about an uploaded mesh file.
"""

import io
from dataclasses import dataclass

import numpy as np
import trimesh


@dataclass
class ParsedMesh:
    vertex_count: int
    face_count: int
    bounds_min: list[float]
    bounds_max: list[float]


def parse_mesh(raw: bytes, source_format: str) -> ParsedMesh:
    mesh = trimesh.load(io.BytesIO(raw), file_type=source_format)

    if isinstance(mesh, trimesh.Scene):
        geometries = list(mesh.geometry.values())
        if not geometries:
            raise ValueError("Mesh file contains no geometry")
        mesh = trimesh.util.concatenate(geometries)

    vertices = np.asarray(mesh.vertices)
    if vertices.size == 0:
        raise ValueError("Mesh file contains no vertices")

    face_count = int(len(mesh.faces)) if hasattr(mesh, "faces") else 0

    return ParsedMesh(
        vertex_count=int(len(vertices)),
        face_count=face_count,
        bounds_min=vertices.min(axis=0).tolist(),
        bounds_max=vertices.max(axis=0).tolist(),
    )
