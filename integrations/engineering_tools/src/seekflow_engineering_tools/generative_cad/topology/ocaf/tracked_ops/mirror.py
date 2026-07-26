"""Tracked Mirror — wraps BRepBuilderAPI_Transform with mirror transform.

1:1 face mapping via builder.Modified(face) — each source face maps to one mirrored face.
"""

from __future__ import annotations

from typing import Any

from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.gp import gp_Trsf, gp_Pnt, gp_Dir, gp_Ax1

from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    EvolutionKind, TopologyEntityKind, ProofClass,
    TopologyCaptureScope, LiveEvolutionBatch, LiveEvolutionRelation, TrackedShapeResult,
)


def tracked_mirror(
    body: Any,
    origin: tuple[float, float, float],
    normal: tuple[float, float, float],
    *,
    scope: TopologyCaptureScope | None = None,
) -> TrackedShapeResult:
    """Mirror a body across a plane defined by origin + normal.

    Uses BRepBuilderAPI_Transform with gp_Trsf.SetMirror().
    Each source face → one mirrored face (MODIFIED, 1:1).

    Args:
        body: CadQuery Shape to mirror.
        origin: Point on the mirror plane (x, y, z).
        normal: Normal vector of the mirror plane (nx, ny, nz).
        scope: TopologyCaptureScope.
    """
    import cadquery as cq

    scope = scope or TopologyCaptureScope()

    trsf = gp_Trsf()
    trsf.SetMirror(gp_Ax1(gp_Pnt(*origin), gp_Dir(*normal)))
    builder = BRepBuilderAPI_Transform(body.wrapped, trsf)
    builder.Build()

    if not builder.IsDone():
        raise RuntimeError("BRepBuilderAPI_Transform (mirror) failed")

    result_shape = builder.Shape()
    result = cq.Shape.cast(result_shape)

    relations: list[LiveEvolutionRelation] = []

    # Per-face history: each source face maps to one mirrored face
    for i, face in enumerate(body.Faces()):
        mod_list = builder.Modified(face.wrapped)
        mod_shapes = tuple(mod_list)
        if mod_shapes:
            relations.append(LiveEvolutionRelation(
                relation_id=f"{scope.node_id}/mirror/mod/face_{i}",
                operation_id=scope.node_id,
                kind=EvolutionKind.MODIFIED,
                entity_kind=TopologyEntityKind.FACE,
                source_key=f"face_{i}",
                old_shape=face.wrapped,
                new_shapes=mod_shapes,
                proof=ProofClass.EXACT_KERNEL_HISTORY,
            ))

    batch = LiveEvolutionBatch(
        scope=scope,
        builder_kind="BRepBuilderAPI_Transform",
        builder_options={
            "operation": "mirror",
            "origin": origin,
            "normal": normal,
        },
        result_shape=result.wrapped,
        context_shape=result.wrapped,
        relations=relations,
        history_complete=len(relations) > 0,
    )
    return TrackedShapeResult(result=result, batch=batch)
