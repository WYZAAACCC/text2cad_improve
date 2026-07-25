"""Tracked Fillet — wraps BRepFilletAPI_MakeFillet with history extraction.

Same pattern as extrude/revolve: uses Generated/Modified directly from the builder.
CadQuery's shapes.fillet() uses the same BRepFilletAPI_MakeFillet internally.

Verified (OCP 7.8.1.1):
- BRepFilletAPI_MakeFillet.Generated(edge) → TopTools_ListOfShape (1 fillet face per edge)
- BRepFilletAPI_MakeFillet.Modified(face) → TopTools_ListOfShape (adjacent faces modified)
"""

from __future__ import annotations

from typing import Any

from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
from OCP.TopoDS import TopoDS

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


def tracked_fillet(
    body: Any,
    edges: list[int],
    radius: float,
    *,
    scope: TopologyCaptureScope | None = None,
) -> TrackedShapeResult:
    """Apply fillet to selected edges with history capture.

    Uses the same BRepFilletAPI_MakeFillet builder as CadQuery.

    Args:
        body: CadQuery Shape to fillet.
        edges: List of 0-based edge indices to fillet.
        radius: Fillet radius in mm.
        scope: TopologyCaptureScope.

    Returns:
        TrackedShapeResult with filleted body and history.
    """
    import cadquery as cq

    scope = scope or TopologyCaptureScope()
    body_faces = list(body.Faces())

    # Get all edges
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_EDGE

    exp = TopExp_Explorer(body.wrapped, TopAbs_EDGE)
    all_edges = []
    while exp.More():
        all_edges.append(exp.Current())
        exp.Next()

    if not edges:
        raise ValueError("No edges specified for fillet")

    # Build the fillet
    builder = BRepFilletAPI_MakeFillet(body.wrapped)

    for edge_idx in edges:
        if edge_idx < 0 or edge_idx >= len(all_edges):
            raise ValueError(
                f"Edge index {edge_idx} out of range (0-{len(all_edges) - 1})"
            )
        edge = TopoDS.Edge_s(all_edges[edge_idx])
        builder.Add(radius, edge)

    builder.Build()  # ★ single execution
    if not builder.IsDone():
        raise RuntimeError("BRepFilletAPI_MakeFillet failed")

    result_shape = builder.Shape()
    result = cq.Shape.cast(result_shape)

    # ── Extract history ──
    relations: list[EvolutionRelation] = []

    # Generated: each filleted edge produces a new fillet face
    for edge_idx in edges:
        edge = TopoDS.Edge_s(all_edges[edge_idx])
        gen_list = builder.Generated(edge)
        if gen_list.Size() > 0:
            relations.append(
                EvolutionRelation(
                    relation_id=f"{scope.node_id}/fillet/gen/edge_{edge_idx}",
                    kind=EvolutionKind.GENERATED,
                    entity_type="face",
                    source_role=f"edge_{edge_idx}",
                    quality=HistoryQuality.EXACT_KERNEL,
                    old_shape_evidence={},
                    new_shape_count=gen_list.Size(),
                )
            )

    # Modified: adjacent faces are modified by the fillet
    for i, face in enumerate(body_faces):
        mod_list = builder.Modified(face.wrapped)
        if mod_list.Size() > 0:
            relations.append(
                EvolutionRelation(
                    relation_id=f"{scope.node_id}/fillet/mod/face_{i}",
                    kind=EvolutionKind.MODIFIED,
                    entity_type="face",
                    source_role=f"face_{i}",
                    quality=HistoryQuality.EXACT_KERNEL,
                    old_shape_evidence=_face_evidence(face),
                    new_shape_count=1,
                )
            )

    batch = TopologyEvolutionBatch(
        scope=scope,
        builder_kind="BRepFilletAPI_MakeFillet",
        builder_options={"radius": radius, "edges": edges},
        result_shape=result.wrapped,
        context_shape=result.wrapped,
        relations=relations,
        history_complete=True,
    )
    return TrackedShapeResult(result=result, capture_token=_stage(batch))
