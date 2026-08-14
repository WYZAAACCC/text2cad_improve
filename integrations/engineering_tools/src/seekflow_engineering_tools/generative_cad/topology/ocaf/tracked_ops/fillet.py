"""Tracked Fillet — wraps BRepFilletAPI_MakeFillet with history extraction.

PR-5 fix: edge_shapes: list[TopoDS_Shape] instead of list[int] (R-06).
Caller must resolve persistent EDGE identity to TopoDS_Shape before calling.
"""

from __future__ import annotations

from typing import Any

from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
from OCP.TopoDS import TopoDS

from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    EvolutionKind, TopologyEntityKind, ProofClass,
    TopologyCaptureScope, LiveEvolutionBatch, LiveEvolutionRelation, TrackedShapeResult,
)


def tracked_fillet(
    body: Any,
    edge_shapes: list[Any],   # ★ TopoDS_Edge shapes, NOT indices
    radius: float,
    *,
    scope: TopologyCaptureScope | None = None,
) -> TrackedShapeResult:
    """Apply fillet to persistent edges with history capture.

    Args:
        body: CadQuery Shape to fillet.
        edge_shapes: List of TopoDS_Edge shapes (NOT indices — resolved via persistent Selection).
        radius: Fillet radius in mm.
        scope: TopologyCaptureScope.
    """
    import cadquery as cq

    scope = scope or TopologyCaptureScope()
    body_faces = list(body.Faces())

    if not edge_shapes:
        raise ValueError("No edge shapes specified for fillet")

    builder = BRepFilletAPI_MakeFillet(body.wrapped)
    for edge_shape in edge_shapes:
        edge = TopoDS.Edge_s(edge_shape)
        builder.Add(radius, edge)

    builder.Build()
    if not builder.IsDone():
        raise RuntimeError("BRepFilletAPI_MakeFillet failed")

    result_shape = builder.Shape()
    result = cq.Shape.cast(result_shape)

    relations: list[LiveEvolutionRelation] = []
    fillet_face = None

    # Generated: each filleted edge produces a fillet face
    for i, edge_shape in enumerate(edge_shapes):
        edge = TopoDS.Edge_s(edge_shape)
        gen_list = builder.Generated(edge)
        gen_shapes = tuple(gen_list)
        if gen_shapes:
            if fillet_face is None:
                fillet_face = gen_shapes[0]
            relations.append(LiveEvolutionRelation(
                relation_id=f"{scope.node_id}/fillet/gen/edge_{i}",
                operation_id=scope.node_id,
                kind=EvolutionKind.GENERATED,
                entity_kind=TopologyEntityKind.FACE,
                source_key=f"edge_{i}",
                old_shape=edge,
                new_shapes=gen_shapes,
                proof=ProofClass.EXACT_KERNEL_HISTORY,
            ))

    # Modified: adjacent faces modified by fillet
    for i, face in enumerate(body_faces):
        mod_list = builder.Modified(face.wrapped)
        mod_shapes = tuple(mod_list)
        if mod_shapes:
            relations.append(LiveEvolutionRelation(
                relation_id=f"{scope.node_id}/fillet/mod/face_{i}",
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
        builder_kind="BRepFilletAPI_MakeFillet",
        builder_options={"radius": radius},
        result_shape=result.wrapped,
        context_shape=result.wrapped,
        relations=relations,
        construction_roles={"fillet": fillet_face},
        history_complete=True,
    )
    return TrackedShapeResult(result=result, batch=batch)
