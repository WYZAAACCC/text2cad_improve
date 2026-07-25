"""Tracked Revolve — drop-in replacement for CadQuery shapes.revolve().

Line-by-line identical to CadQuery 2.7.0 shapes.revolve(), with History extraction
from the BRepPrimAPI_MakeRevol builder after Build().

Verified (OCP 7.8.1.1):
- BRepPrimAPI_MakeRevol has Generated()/Modified()/FirstShape()/LastShape()
- BUT does NOT have History() method (same pattern as MakePrism)
- Generated(profile_face) → TopTools_ListOfShape of generated faces

CadQuery source: shapes.revolve(s, p, d, a) → _get → BRepPrimAPI_MakeRevol → Build → _compound_or_shape
"""

from __future__ import annotations

import math
from typing import Any

from cadquery.occ_impl.shapes import (
    _compound_or_shape,
    _get,
    Vector,
)
from OCP.BRepPrimAPI import BRepPrimAPI_MakeRevol
from OCP.gp import gp_Ax1

from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    EvolutionKind,
    EvolutionRelation,
    HistoryQuality,
    TopologyCaptureScope,
    TopologyEvolutionBatch,
    TrackedShapeResult,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.boolean import (
    _stage,
    _face_evidence,
)


def tracked_revolve(
    profile: Any,
    axis_origin: tuple[float, float, float] | list[float],
    axis_dir: tuple[float, float, float] | list[float],
    angle_deg: float = 360.0,
    *,
    scope: TopologyCaptureScope | None = None,
) -> TrackedShapeResult:
    """Drop-in replacement for shapes.revolve() with History capture.

    Identical to CadQuery 2.7.0 shapes.revolve() line-by-line.
    History is extracted from BRepPrimAPI_MakeRevol.Generated/Modified/FirstShape/LastShape.

    Args:
        profile: CadQuery Shape (Face, Wire, Edge, Vertex, or Compound thereof)
        axis_origin: Point on the rotation axis (x, y, z)
        axis_dir: Direction vector of the rotation axis (x, y, z)
        angle_deg: Rotation angle in degrees (default 360)
        scope: TopologyCaptureScope for this operation
    """
    import math as _math
    from math import radians as _radians

    results: list[Any] = []
    relations: list[EvolutionRelation] = []
    first_shape = None
    last_shape = None

    scope = scope or TopologyCaptureScope()

    ax = gp_Ax1(Vector(axis_origin).toPnt(), Vector(axis_dir).toDir())

    for el in _get(profile, ("Vertex", "Edge", "Wire", "Face")):
        builder = BRepPrimAPI_MakeRevol(el.wrapped, ax, _radians(angle_deg))
        builder.Build()  # ★ single execution
        result_shape = builder.Shape()
        results.append(result_shape)

        el_type = el.ShapeType()

        # ── History extraction (same pattern as MakePrism) ──
        if el_type == "Wire":
            for edge in el.Edges():
                gen_list = builder.Generated(edge.wrapped)
                if gen_list.Size() > 0:
                    relations.append(
                        EvolutionRelation(
                            relation_id=f"{scope.node_id}/revolve/gen/{len(relations)}",
                            kind=EvolutionKind.GENERATED,
                            entity_type="face",
                            source_role="profile_edge",
                            quality=HistoryQuality.EXACT_KERNEL,
                            old_shape_evidence=_face_evidence(edge),
                            new_shape_count=gen_list.Size(),
                        )
                    )
                mod_list = builder.Modified(edge.wrapped)
                if mod_list.Size() > 0:
                    relations.append(
                        EvolutionRelation(
                            relation_id=f"{scope.node_id}/revolve/mod/{len(relations)}",
                            kind=EvolutionKind.MODIFIED,
                            entity_type="edge",
                            source_role="profile_edge",
                            quality=HistoryQuality.EXACT_KERNEL,
                            old_shape_evidence=_face_evidence(edge),
                            new_shape_count=1,
                        )
                    )

        elif el_type == "Face":
            gen_list = builder.Generated(el.wrapped)
            if gen_list.Size() > 0:
                relations.append(
                    EvolutionRelation(
                        relation_id=f"{scope.node_id}/revolve/gen/{len(relations)}",
                        kind=EvolutionKind.GENERATED,
                        entity_type="face",
                        source_role="profile_face",
                        quality=HistoryQuality.EXACT_KERNEL,
                        old_shape_evidence=_face_evidence(el),
                        new_shape_count=gen_list.Size(),
                    )
                )
            mod_list = builder.Modified(el.wrapped)
            if mod_list.Size() > 0:
                relations.append(
                    EvolutionRelation(
                        relation_id=f"{scope.node_id}/revolve/mod/{len(relations)}",
                        kind=EvolutionKind.MODIFIED,
                        entity_type="face",
                        source_role="profile_face",
                        quality=HistoryQuality.EXACT_KERNEL,
                        old_shape_evidence=_face_evidence(el),
                        new_shape_count=1,
                    )
                )

        if first_shape is None:
            first_shape = builder.FirstShape()
        last_shape = builder.LastShape()

    result = _compound_or_shape(results)

    batch = TopologyEvolutionBatch(
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
        first_shape=first_shape,
        last_shape=last_shape,
        history_complete=True,
    )
    return TrackedShapeResult(result=result, capture_token=_stage(batch))
