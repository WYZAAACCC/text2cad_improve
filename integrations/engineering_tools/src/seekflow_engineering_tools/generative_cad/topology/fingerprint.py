"""Topology fingerprint — constrained geometric signature for fallback matching.

Phase 1: data model definitions only. No computation yet.
Phase 3+: actual fingerprint computation + constrained bipartite matching.

Design constraints (from document §10.3, §11.4):
  - Fingerprint matching is ALWAYS constrained by provenance, component,
    entity type, and lineage BEFORE geometric comparison.
  - Never do global nearest-centroid matching.
  - If best/second-best score margin < threshold → ambiguous (not auto-pick).
  - Cost function: C = w_provenance * P + w_type * T + w_adjacency * A
                       + w_geometry * G + w_location * L

Quantization: all geometric values rounded to tolerance units before
comparison. Never compare raw floating-point strings.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class FaceFingerprint(BaseModel):
    """Lightweight geometric signature of a face.

    All continuous values are quantized (rounded to tolerance units).
    Phase 1: schema only. Phase 3+: compute from OCP TopoDS_Face.
    """

    model_config = ConfigDict(extra="forbid")

    surface_type: str = "unknown"

    # Quantized geometry (all ints — tolerance-unit rounded)
    area_q: int | None = None
    centroid_q: tuple[int, int, int] | None = None
    bbox_q: tuple[int, int, int, int, int, int] | None = None

    # Normal or axis (quantized direction vector)
    normal_or_axis_q: tuple[int, int, int] | None = None

    # Surface-specific quantized params
    plane_offset_q: int | None = None
    radius_q: int | None = None
    major_radius_q: int | None = None
    minor_radius_q: int | None = None

    # Topology counts
    boundary_wire_count: int = 0
    boundary_edge_count: int = 0

    # Adjacency signatures (stable across small param changes)
    adjacent_face_signatures: list[str] = []
    adjacent_edge_curve_types: list[str] = []

    # Convexity of each bounding edge
    convexity_signature: list[
        Literal["convex", "concave", "smooth", "unknown"]
    ] = []

    # Provenance anchor (ties this fingerprint to its producer)
    provenance_anchor: str = ""


class EdgeFingerprint(BaseModel):
    """Lightweight geometric signature of an edge.

    All continuous values quantized. Phase 1: schema only.
    """

    model_config = ConfigDict(extra="forbid")

    curve_type: str = "unknown"

    # Quantized geometry
    length_q: int | None = None
    centroid_q: tuple[int, int, int] | None = None
    bbox_q: tuple[int, int, int, int, int, int] | None = None

    # Direction or axis
    direction_or_axis_q: tuple[int, int, int] | None = None
    radius_q: int | None = None

    # Endpoint valences (face counts at each endpoint)
    endpoint_valences: tuple[int, int] = (0, 0)

    # Adjacent face types + IDs
    adjacent_face_surface_types: list[str] = []
    adjacent_face_ids: list[str] = []

    # Provenance anchor
    provenance_anchor: str = ""


# ═══════════════════════════════════════════════════════════════════════════════
# Fingerprint computation (Phase 5)
# ═══════════════════════════════════════════════════════════════════════════════


def compute_face_fingerprint(
    face: "Any",
    tolerance_mm: float = 0.01,
    provenance_anchor: str = "",
) -> FaceFingerprint:
    """Compute a quantized geometric fingerprint from a CadQuery/OCP face.

    All continuous values are quantized: q = round(value / tolerance_mm).
    This ensures that small parameter changes (< tolerance) don't alter
    the fingerprint, while larger changes do.

    Args:
        face: A CadQuery Face object (has geomType(), Area(), Center(), etc.).
        tolerance_mm: Quantization tolerance in mm (default 0.01mm = 10μm).
        provenance_anchor: Optional provenance string (e.g. "box/n1/face").

    Returns:
        FaceFingerprint with quantized geometric properties.
    """
    tol = float(tolerance_mm)
    if tol <= 0:
        tol = 0.01

    # Surface type
    try:
        surface_type = str(face.geomType())
    except Exception:
        surface_type = "unknown"

    # Area
    try:
        area = float(face.Area())
        area_q = round(area / tol)
    except Exception:
        area_q = None

    # Centroid
    try:
        c = face.Center()
        centroid_q = (round(c.x / tol), round(c.y / tol), round(c.z / tol))
    except Exception:
        centroid_q = None

    # Bounding box
    try:
        bb = face.BoundingBox()
        bbox_q = (
            round(bb.xmin / tol), round(bb.ymin / tol), round(bb.zmin / tol),
            round(bb.xmax / tol), round(bb.ymax / tol), round(bb.zmax / tol),
        )
    except Exception:
        bbox_q = None

    # Normal or axis
    normal_or_axis_q = None
    plane_offset_q = None
    radius_q = None

    try:
        if surface_type == "PLANE":
            n = face.normalAt()
            normal_or_axis_q = (round(n.x), round(n.y), round(n.z))
            if c is not None:
                plane_offset_q = round((n.x * c.x + n.y * c.y + n.z * c.z) / tol)
        elif surface_type in ("CYLINDER", "SPHERE"):
            # Approximate radius from area: A = 2πrh (cylinder) or A = 4πr² (sphere)
            import math
            n = face.normalAt()
            normal_or_axis_q = (round(n.x), round(n.y), round(n.z))
            if area is not None and area > 0:
                if surface_type == "SPHERE":
                    r_approx = math.sqrt(area / (4.0 * math.pi))
                else:
                    r_approx = area / (2.0 * math.pi * max((bb.zmax - bb.zmin) if bbox_q else 1.0, 1.0))
                radius_q = round(r_approx / tol)
    except Exception:
        pass

    # Boundary counts
    boundary_wire_count = 0
    boundary_edge_count = 0
    try:
        wires = face.Wires()
        boundary_wire_count = len(list(wires)) if hasattr(wires, '__iter__') else 0
        edges = face.Edges()
        boundary_edge_count = len(list(edges)) if hasattr(edges, '__iter__') else 0
    except Exception:
        pass

    return FaceFingerprint(
        surface_type=surface_type,
        area_q=area_q,
        centroid_q=centroid_q,
        bbox_q=bbox_q,
        normal_or_axis_q=normal_or_axis_q,
        plane_offset_q=plane_offset_q,
        radius_q=radius_q,
        boundary_wire_count=boundary_wire_count,
        boundary_edge_count=boundary_edge_count,
        provenance_anchor=provenance_anchor,
    )
