"""Tracked Revolve — drop-in replacement for CadQuery shapes.revolve().

Line-by-line identical to CadQuery 2.7.0 shapes.revolve(), with History extraction
from the BRepPrimAPI_MakeRevol builder after Build().

PR-2: Collects REAL TopoDS_Shape handles into LiveEvolutionRelation.
"""

from __future__ import annotations

from typing import Any

from cadquery.occ_impl.shapes import (
    _compound_or_shape,
    _get,
    Vector,
)
from OCP.BRepPrimAPI import BRepPrimAPI_MakeRevol
from OCP.gp import gp_Ax1

from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.extrude import (
    _find_cap_faces,
    _remaining_face_roles,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    EvolutionKind,
    LiveEvolutionBatch,
    LiveEvolutionRelation,
    ProofClass,
    TopologyCaptureScope,
    TopologyEntityKind,
    TrackedShapeResult,
)


def tracked_revolve(
    profile: Any,
    axis_origin: tuple[float, float, float] | list[float],
    axis_dir: tuple[float, float, float] | list[float],
    angle_deg: float = 360.0,
    *,
    scope: TopologyCaptureScope | None = None,
) -> TrackedShapeResult:
    """Drop-in replacement for shapes.revolve() with History capture."""
    from math import radians as _radians

    results: list[Any] = []
    relations: list[LiveEvolutionRelation] = []

    scope = scope or TopologyCaptureScope()
    ax = gp_Ax1(Vector(axis_origin).toPnt(), Vector(axis_dir).toDir())

    for el in _get(profile, ("Vertex", "Edge", "Wire", "Face")):
        builder = BRepPrimAPI_MakeRevol(el.wrapped, ax, _radians(angle_deg))
        builder.Build()
        result_shape = builder.Shape()
        results.append(result_shape)

        el_type = el.ShapeType()

        if el_type == "Wire":
            for edge in el.Edges():
                _capture_generated(relations, scope, builder, edge, "profile_edge")
                _capture_modified(relations, scope, builder, edge, "profile_edge")

        elif el_type == "Face":
            _capture_generated(relations, scope, builder, el, "profile_face")
            _capture_modified(relations, scope, builder, el, "profile_face")

    result = _compound_or_shape(results)
    start_cap, end_cap = _find_cap_faces(result, axis_dir)
    side_roles = _find_revolve_side_faces(result)
    construction_roles = {
        "start_cap": start_cap,
        "end_cap": end_cap,
        **side_roles,
    }
    face_roles = _remaining_face_roles(result, construction_roles, "revolve")

    batch = LiveEvolutionBatch(
        scope=scope,
        builder_kind="BRepPrimAPI_MakeRevol",
        builder_options={
            "axis_origin": tuple(float(v) for v in axis_origin),
            "axis_dir": tuple(float(v) for v in axis_dir),
            "angle_deg": float(angle_deg),
        },
        result_shape=result.wrapped,
        context_shape=result.wrapped,
        relations=relations,
        construction_roles=construction_roles,
        face_roles=face_roles,
        history_complete=True,
    )
    return TrackedShapeResult(result=result, batch=batch)


def _find_revolve_side_faces(result: Any):
    """Classify full-revolution side faces into rim, bore, and web.

    For a 360-degree revolve around Z, cylindrical faces are the radial
    surfaces. The one with the largest radius is the rim; the one with the
    smallest radius is the bore (present only when the profile has a center
    hole). Conical side faces are the web (single-web semantic for now).
    """
    from OCP.BRepAdaptor import BRepAdaptor_Surface

    cylinders: list[tuple[float, Any]] = []
    cones: list[Any] = []
    for f in result.Faces():
        try:
            adaptor = BRepAdaptor_Surface(f.wrapped)
            if adaptor.GetType() == 1:  # GeomAbs_Cylinder
                radius = float(adaptor.Cylinder().Radius())
                cylinders.append((radius, f.wrapped))
            elif adaptor.GetType() == 2:  # GeomAbs_Cone
                cones.append(f.wrapped)
        except Exception:
            continue

    rim = None
    bore = None
    if cylinders:
        cylinders.sort(key=lambda p: p[0])
        rim = cylinders[-1][1]
        bore = cylinders[0][1] if len(cylinders) >= 2 else None
    web = cones[0] if cones else None
    return {"rim": rim, "bore": bore, "web": web}


def _capture_generated(relations, scope, builder, element, source_role):
    gen_list = builder.Generated(element.wrapped)
    gen_shapes = tuple(gen_list)
    if gen_shapes:
        relations.append(
            LiveEvolutionRelation(
                relation_id=f"{scope.node_id}/revolve/gen/{len(relations)}",
                operation_id=scope.node_id,
                kind=EvolutionKind.GENERATED,
                entity_kind=TopologyEntityKind.FACE,
                source_key=source_role,
                old_shape=element.wrapped,
                new_shapes=gen_shapes,
                proof=ProofClass.EXACT_KERNEL_HISTORY,
            )
        )


def _capture_modified(relations, scope, builder, element, source_role):
    mod_list = builder.Modified(element.wrapped)
    mod_shapes = tuple(mod_list)
    if mod_shapes:
        relations.append(
            LiveEvolutionRelation(
                relation_id=f"{scope.node_id}/revolve/mod/{len(relations)}",
                operation_id=scope.node_id,
                kind=EvolutionKind.MODIFIED,
                entity_kind=TopologyEntityKind.FACE,
                source_key=source_role,
                old_shape=element.wrapped,
                new_shapes=mod_shapes,
                proof=ProofClass.EXACT_KERNEL_HISTORY,
            )
        )
