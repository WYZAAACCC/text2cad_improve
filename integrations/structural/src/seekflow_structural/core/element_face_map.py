"""Which element faces make up a selected CAD face.

A pressure load has to name the element and the local face it acts on -
`SFE, elem, lkey, PRES, 0, p`. The selection stage produces the opposite kind
of thing: a set of CAD (OCC) faces, and for each one the mesh *nodes* that lie
on it. Nothing in the pipeline bridged the two, which is why the load was
applied as forces at nodes instead.

This module builds that bridge geometrically, from the mesh alone. A
tetrahedron's corner face lies on a planar selected face exactly when all
three of its corner nodes are on that face; the face's own normal then
confirms it, which rejects a non-selected face that happens to lie in the same
plane.

Corner nodes only, deliberately. The mid-side nodes cannot make the test more
selective - they sit on edges shared with neighbouring faces - and they are not
needed for the area either, because the mesh is generated with
`Mesh.SecondOrderLinear=1` so a six-node face is geometrically flat and the
corner triangle's area is the whole face's area. Mid-side nodes receive the
pressure from ANSYS, not from here.

The outward normal is computed from element geometry, signed away from the
fourth corner, and never from the OCC face. That is what lets the load audit
be independent of the normal it is checking.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path

# Which corner triple of a SOLID187 belongs to which local face number, and
# therefore which LKEY to pass to SFE. Measured, not remembered: see
# probes/solid187_face_probe, which loaded each LKEY on a known tetrahedron and
# read back which nodes carried the load. Indices are into the element's
# corner nodes I, J, K, L in the order the element is defined.
SOLID187_FACE_LKEY = {
    frozenset({0, 1, 2}): 1,  # I J K
    frozenset({0, 1, 3}): 2,  # I J L
    frozenset({1, 2, 3}): 3,  # J K L
    frozenset({0, 2, 3}): 4,  # K I L
}
SOLID187_FACE_PROBE = "probes/solid187_face_probe/probe_report.json"

# A positive PRES pushes into the element. The probe confirmed this on every
# face, so the load direction needs no arithmetic of its own.
POSITIVE_PRESSURE_DIRECTION = "into_element"

# How closely the mesh-derived normal must agree with the OCC normal for a
# corner triple to be accepted. A plane test alone would accept a
# non-selected face lying in the same plane; the normal separates them.
NORMAL_TOLERANCE = 0.999

# Corner-node index triples of a tetrahedron: all four ways to omit one node.
_FACE_TRIPLES = ((0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3))


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(a):
    return math.sqrt(_dot(a, a))


def _unit(a):
    length = _norm(a)
    if length <= 0:
        return (0.0, 0.0, 0.0)
    return (a[0] / length, a[1] / length, a[2] / length)


def read_mesh(mesh_inp: Path):
    """Nodes and element connectivity from the APDL mesh the mesher writes.

    `EMORE` does not mean what its name suggests. `mesh_sector.py` writes
    `EN,<eid>,<n1..n8>` followed by `EMORE,<n9>,<n10>` - the two fields are
    more *node* ids, not an element id and a node id. Reading it as
    `EMORE,<eid>,<n10>` produces a connectivity that is silently wrong for
    most elements and right for a few, which is the worst of both.
    """
    nodes: dict[int, tuple[float, float, float]] = {}
    elements: dict[int, list[int]] = {}
    pending: int | None = None

    for line in mesh_inp.read_text(
        encoding="utf-8", errors="replace"
    ).splitlines():
        if line.startswith("N,"):
            parts = line.strip().split(",")
            if len(parts) != 5:
                continue
            try:
                nodes[int(parts[1])] = (
                    float(parts[2]), float(parts[3]), float(parts[4])
                )
            except ValueError:
                continue
        elif line.startswith("EN,"):
            parts = line.strip().split(",")
            if len(parts) < 10:
                continue
            try:
                element = int(parts[1])
                elements[element] = [int(v) for v in parts[2:10]]
                pending = element
            except ValueError:
                pending = None
        elif line.startswith("EMORE,"):
            if pending is None:
                continue
            parts = line.strip().split(",")
            if len(parts) < 3:
                continue
            try:
                elements[pending].extend([int(parts[1]), int(parts[2])])
            except ValueError:
                pass
            pending = None
    return nodes, elements


@dataclass
class ElementFace:
    elem: int
    lkey: int
    corner_nodes: tuple[int, int, int]
    area_mm2: float
    outward_normal: tuple[float, float, float]
    centroid_mm: tuple[float, float, float]


@dataclass
class FaceMap:
    faces: dict[int, list[ElementFace]] = dataclass_field(default_factory=dict)
    occ_area_mm2_by_face: dict[int, float] = dataclass_field(default_factory=dict)
    occ_normal_by_face: dict[int, tuple] = dataclass_field(default_factory=dict)
    ambiguous_by_face: dict[int, int] = dataclass_field(default_factory=dict)
    rejected_by_normal_by_face: dict[int, int] = dataclass_field(
        default_factory=dict
    )
    limits: list[str] = dataclass_field(default_factory=list)

    def mapped_area_mm2(self, face_index: int) -> float:
        return sum(face.area_mm2 for face in self.faces.get(face_index, ()))

    def mapped_area_total_mm2(self) -> float:
        return sum(face.area_mm2 for faces in self.faces.values() for face in faces)

    def occ_area_total_mm2(self) -> float:
        return sum(self.occ_area_mm2_by_face.values())

    def element_face_count(self) -> int:
        return sum(len(faces) for faces in self.faces.values())

    def normal_agreement_min(self) -> float | None:
        agreements = [
            _dot(face.outward_normal, self.occ_normal_by_face[face_index])
            for face_index, faces in self.faces.items()
            for face in faces
            if face_index in self.occ_normal_by_face
        ]
        return round(min(agreements), 6) if agreements else None

    def to_audit(self) -> dict:
        occ_total = self.occ_area_total_mm2()
        mapped_total = self.mapped_area_total_mm2()
        return {
            "element_face_count": self.element_face_count(),
            "mapped_area_total_mm2": round(mapped_total, 4),
            "occ_area_total_mm2": round(occ_total, 4),
            "mapped_area_fraction": (
                round(mapped_total / occ_total, 6) if occ_total else None
            ),
            "uncovered_area_mm2": round(occ_total - mapped_total, 4),
            "normal_agreement_min": self.normal_agreement_min(),
            "ambiguous_element_face_count": sum(self.ambiguous_by_face.values()),
            "rejected_by_normal_count": sum(
                self.rejected_by_normal_by_face.values()
            ),
            "lkey_table": {
                "IJK": 1, "IJL": 2, "JKL": 3, "KIL": 4,
            },
            "lkey_table_evidence": SOLID187_FACE_PROBE,
            "pressure_direction": POSITIVE_PRESSURE_DIRECTION,
            "limits": self.limits,
        }

    def per_face_audit(self) -> dict:
        out = {}
        for face_index, occ_area in self.occ_area_mm2_by_face.items():
            mapped = self.mapped_area_mm2(face_index)
            out[str(face_index)] = {
                "element_face_count": len(self.faces.get(face_index, ())),
                "mapped_area_mm2": round(mapped, 4),
                "occ_area_mm2": round(occ_area, 4),
                "mapped_area_fraction": (
                    round(mapped / occ_area, 6) if occ_area else None
                ),
                "ambiguous_count": self.ambiguous_by_face.get(face_index, 0),
                "rejected_by_normal_count": self.rejected_by_normal_by_face.get(
                    face_index, 0
                ),
            }
        return out


def build(
    nodes: dict[int, tuple[float, float, float]],
    elements: dict[int, list[int]],
    selection: dict,
    normal_tolerance: float = NORMAL_TOLERANCE,
) -> FaceMap:
    """Map every selected CAD face onto the element faces that lie on it."""
    mapping = FaceMap()
    per_face = selection.get("per_face") or {}

    node_sets: dict[int, set[int]] = {}
    for key, row in per_face.items():
        face_index = int(key)
        node_sets[face_index] = {int(v) for v in row.get("node_ids", ())}
        mapping.occ_area_mm2_by_face[face_index] = float(row.get("area_mm2") or 0.0)
        normal = row.get("normal_xyz")
        if normal is None:
            mapping.limits.append(
                f"selected face {face_index} carries no normal_xyz, so no "
                "element face on it can be confirmed; re-run the face-to-node "
                "mapping to regenerate the selection"
            )
            continue
        mapping.occ_normal_by_face[face_index] = _unit(
            (float(normal[0]), float(normal[1]), float(normal[2]))
        )
        mapping.faces[face_index] = []

    for element, connectivity in elements.items():
        if len(connectivity) < 4:
            continue
        corners = [connectivity[index] for index in range(4)]
        if any(node not in nodes for node in corners):
            continue
        for triple in _FACE_TRIPLES:
            three = tuple(corners[index] for index in triple)
            if any(node not in nodes for node in three):
                continue
            missing = next(index for index in range(4) if index not in triple)
            fourth = corners[missing]

            a, b, c = (nodes[node] for node in three)
            cross = _cross(_sub(b, a), _sub(c, a))
            area = 0.5 * _norm(cross)
            if area <= 0:
                continue
            centroid = tuple((a[i] + b[i] + c[i]) / 3.0 for i in range(3))
            normal = _unit(cross)
            # Signed away from the fourth corner, so it points out of the
            # element whichever way the triple happened to be ordered.
            if _dot(normal, _sub(nodes[fourth], centroid)) > 0:
                normal = (-normal[0], -normal[1], -normal[2])

            candidates = []
            for face_index, node_set in node_sets.items():
                if not all(node in node_set for node in three):
                    continue
                occ_normal = mapping.occ_normal_by_face.get(face_index)
                if occ_normal is None:
                    continue
                agreement = _dot(normal, occ_normal)
                if agreement >= normal_tolerance:
                    candidates.append(face_index)
                else:
                    mapping.rejected_by_normal_by_face[face_index] = (
                        mapping.rejected_by_normal_by_face.get(face_index, 0) + 1
                    )

            if len(candidates) > 1:
                # Two selected faces share this element face. Picking one would
                # be a guess about which face the load belongs to, and the
                # resultant would not reveal it.
                for face_index in candidates:
                    mapping.ambiguous_by_face[face_index] = (
                        mapping.ambiguous_by_face.get(face_index, 0) + 1
                    )
                continue
            if not candidates:
                continue

            face_index = candidates[0]
            mapping.faces[face_index].append(
                ElementFace(
                    elem=element,
                    lkey=SOLID187_FACE_LKEY[frozenset(triple)],
                    corner_nodes=three,
                    area_mm2=area,
                    outward_normal=normal,
                    centroid_mm=centroid,
                )
            )

    empty = [
        face_index
        for face_index, faces in mapping.faces.items()
        if not faces
    ]
    if empty:
        mapping.limits.append(
            f"selected face(s) {sorted(empty)} produced no element face. "
            "Either the mesh does not reach them, or they are not planar - "
            "the face-to-node mapping only handles planes, so a curved "
            "selected face maps to nothing and must be reported rather than "
            "loaded with an empty set"
        )
    for face_index, count in sorted(mapping.ambiguous_by_face.items()):
        if count:
            mapping.limits.append(
                f"{count} element face(s) lie on selected face {face_index} "
                "and at least one other selected face; they are excluded "
                "because which face the traction belongs to cannot be told "
                "from the geometry alone"
            )
    return mapping
