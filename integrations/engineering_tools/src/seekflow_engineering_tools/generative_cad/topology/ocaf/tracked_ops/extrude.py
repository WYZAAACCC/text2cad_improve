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
    first_shape = None
    last_shape = None

    scope = scope or TopologyCaptureScope()

    for el in _get(profile, ("Vertex", "Edge", "Wire", "Face")):
        builder = BRepPrimAPI_MakePrism(el.wrapped, Vector(vector).wrapped)
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

        if first_shape is None:
            first_shape = builder.FirstShape()
        last_shape = builder.LastShape()

    result = _compound_or_shape(results)

    batch = LiveEvolutionBatch(
        scope=scope,
        builder_kind="BRepPrimAPI_MakePrism",
        builder_options={"vector": tuple(float(v) for v in vector)},
        result_shape=result.wrapped,
        context_shape=result.wrapped,
        relations=relations,
        construction_roles={
            "start_cap": first_shape,
            "end_cap": last_shape,
        },
        history_complete=True,
    )
    return TrackedShapeResult(result=result, batch=batch)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _capture_generated(
    relations: list[LiveEvolutionRelation],
    scope: TopologyCaptureScope,
    builder: Any,
    element: Any,
    source_role: str,
) -> None:
    gen_list = builder.Generated(element.wrapped)
    gen_shapes = tuple(gen_list)
    if gen_shapes:
        relations.append(
            LiveEvolutionRelation(
                relation_id=f"{scope.node_id}/extrude/gen/{len(relations)}",
                operation_id=scope.node_id,
                kind=EvolutionKind.GENERATED,
                entity_kind=TopologyEntityKind.FACE,
                source_key=source_role,
                old_shape=element.wrapped,
                new_shapes=gen_shapes,
                proof=ProofClass.EXACT_KERNEL_HISTORY,
            )
        )


def _capture_modified(
    relations: list[LiveEvolutionRelation],
    scope: TopologyCaptureScope,
    builder: Any,
    element: Any,
    source_role: str,
) -> None:
    mod_list = builder.Modified(element.wrapped)
    mod_shapes = tuple(mod_list)
    if mod_shapes:
        relations.append(
            LiveEvolutionRelation(
                relation_id=f"{scope.node_id}/extrude/mod/{len(relations)}",
                operation_id=scope.node_id,
                kind=EvolutionKind.MODIFIED,
                entity_kind=TopologyEntityKind.FACE,
                source_key=source_role,
                old_shape=element.wrapped,
                new_shapes=mod_shapes,
                proof=ProofClass.EXACT_KERNEL_HISTORY,
            )
        )
