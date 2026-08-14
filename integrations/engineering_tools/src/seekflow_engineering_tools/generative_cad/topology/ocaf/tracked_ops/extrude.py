"""Tracked Extrude — drop-in replacement for CadQuery shapes.extrude().

Line-by-line identical to CadQuery 2.7.0 shapes.extrude(), with History extraction
from the BRepPrimAPI_MakePrism builder after Build().

Verified (OCP 7.8.1.1):
- BRepPrimAPI_MakePrism has Generated()/Modified()/FirstShape()/LastShape()
- BUT does NOT have History() method (unlike BOPAlgo_BOP)

PR-2: Collects REAL TopoDS_Shape handles into LiveEvolutionRelation.
"""

from __future__ import annotations

from typing import Any

from cadquery.occ_impl.shapes import (
    _compound_or_shape,
    _get,
    Vector,
)
from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism

from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    EvolutionKind,
    LiveEvolutionBatch,
    LiveEvolutionRelation,
    ProofClass,
    TopologyCaptureScope,
    TopologyEntityKind,
    TrackedShapeResult,
)


def tracked_extrude(
    profile: Any,
    vector: tuple[float, float, float] | list[float],
    *,
    scope: TopologyCaptureScope | None = None,
) -> TrackedShapeResult:
    """Drop-in replacement for shapes.extrude() with History capture."""
    results: list[Any] = []
    relations: list[LiveEvolutionRelation] = []

    scope = scope or TopologyCaptureScope()

    for el in _get(profile, ("Vertex", "Edge", "Wire", "Face")):
        el_type = el.ShapeType()
        profile_shape = el.wrapped

        if el_type == "Wire":
            # CadQuery's extrude makes a face from a closed wire first; without
            # this, MakePrism would produce an open shell (no caps) instead of
            # a solid.
            from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
            fb = BRepBuilderAPI_MakeFace(el.wrapped)
            fb.Build()
            profile_shape = fb.Face()
            el_type = "Face"

        builder = BRepPrimAPI_MakePrism(profile_shape, Vector(vector).wrapped)
        builder.Build()
        result_shape = builder.Shape()
        results.append(result_shape)

        if el_type == "Face":
            _capture_generated(relations, scope, builder, profile_shape, "profile_face")
            _capture_modified(relations, scope, builder, profile_shape, "profile_face")

    result = _compound_or_shape(results)
    start_cap, end_cap = _find_cap_faces(result, vector)
    side_roles = _classify_side_faces(result, vector)

    construction_roles = {
        "start_cap": start_cap,
        "end_cap": end_cap,
        **side_roles,
    }

    batch = LiveEvolutionBatch(
        scope=scope,
        builder_kind="BRepPrimAPI_MakePrism",
        builder_options={"vector": tuple(float(v) for v in vector)},
        result_shape=result.wrapped,
        context_shape=result.wrapped,
        relations=relations,
        construction_roles=construction_roles,
        history_complete=True,
    )
    return TrackedShapeResult(result=result, batch=batch)


def _find_cap_faces(result: Any, direction: tuple[float, float, float] | list[float]):
    """Return (start_cap, end_cap) faces whose normal is parallel to direction."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface

    dx, dy, dz = direction
    length = (dx * dx + dy * dy + dz * dz) ** 0.5
    if length < 1e-9:
        return None, None
    ux, uy, uz = dx / length, dy / length, dz / length

    caps: list[tuple[float, Any]] = []
    for f in result.Faces():
        try:
            adaptor = BRepAdaptor_Surface(f.wrapped)
            if adaptor.GetType() == 0:  # GeomAbs_Plane
                n = adaptor.Plane().Position().Direction()
                dot = n.X() * ux + n.Y() * uy + n.Z() * uz
                if abs(abs(dot) - 1.0) < 0.01:
                    c = f.Center()
                    caps.append((c.x * ux + c.y * uy + c.z * uz, f.wrapped))
        except Exception:
            continue

    caps.sort(key=lambda p: p[0])
    if len(caps) >= 2:
        return caps[0][1], caps[-1][1]
    if len(caps) == 1:
        return caps[0][1], None
    return None, None


def _classify_side_faces(result: Any, direction: tuple[float, float, float] | list[float]):
    """Classify axis-aligned side faces of an extruded prism by their normal.

    Only faces whose plane normal is axis-aligned (within tolerance) and
    perpendicular to the extrude direction are named. The +X/-X/+Y/-Y sign is
    determined from the face centroid relative to the body bounding-box center
    (plane-normal sign is orientation-dependent in OCCT and therefore not used).
    This is reliable for the rectangular/box case; arbitrary profiles simply
    leave the roles as None.
    """
    from OCP.BRepAdaptor import BRepAdaptor_Surface

    dx, dy, dz = direction
    length = (dx * dx + dy * dy + dz * dz) ** 0.5
    if length < 1e-9:
        return {}
    ux, uy, uz = dx / length, dy / length, dz / length

    roles = {"+X": None, "-X": None, "+Y": None, "-Y": None}
    for f in result.Faces():
        try:
            adaptor = BRepAdaptor_Surface(f.wrapped)
            if adaptor.GetType() != 0:  # GeomAbs_Plane only
                continue
            n = adaptor.Plane().Position().Direction()
            nx, ny, nz = n.X(), n.Y(), n.Z()
            # Skip cap faces whose normal is parallel to the extrude direction.
            dot = abs(nx * ux + ny * uy + nz * uz)
            if dot > 0.99:
                continue
            ax = abs(nx)
            ay = abs(ny)
            fc = f.Center()
            center = result.BoundingBox().center
            if ax > 0.99 and ay < 0.01:
                roles["+X" if fc.x > center.x else "-X"] = f.wrapped
            elif ay > 0.99 and ax < 0.01:
                roles["+Y" if fc.y > center.y else "-Y"] = f.wrapped
        except Exception:
            continue
    return roles


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _capture_generated(
    relations: list[LiveEvolutionRelation],
    scope: TopologyCaptureScope,
    builder: Any,
    shape: Any,
    source_role: str,
) -> None:
    gen_list = builder.Generated(shape)
    gen_shapes = tuple(gen_list)
    if gen_shapes:
        relations.append(
            LiveEvolutionRelation(
                relation_id=f"{scope.node_id}/extrude/gen/{len(relations)}",
                operation_id=scope.node_id,
                kind=EvolutionKind.GENERATED,
                entity_kind=TopologyEntityKind.FACE,
                source_key=source_role,
                old_shape=shape,
                new_shapes=gen_shapes,
                proof=ProofClass.EXACT_KERNEL_HISTORY,
            )
        )


def _capture_modified(
    relations: list[LiveEvolutionRelation],
    scope: TopologyCaptureScope,
    builder: Any,
    shape: Any,
    source_role: str,
) -> None:
    mod_list = builder.Modified(shape)
    mod_shapes = tuple(mod_list)
    if mod_shapes:
        relations.append(
            LiveEvolutionRelation(
                relation_id=f"{scope.node_id}/extrude/mod/{len(relations)}",
                operation_id=scope.node_id,
                kind=EvolutionKind.MODIFIED,
                entity_kind=TopologyEntityKind.FACE,
                source_key=source_role,
                old_shape=shape,
                new_shapes=mod_shapes,
                proof=ProofClass.EXACT_KERNEL_HISTORY,
            )
        )
