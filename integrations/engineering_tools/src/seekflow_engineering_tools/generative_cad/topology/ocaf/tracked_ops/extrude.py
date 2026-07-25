"""Tracked Extrude — drop-in replacement for CadQuery shapes.extrude().

Line-by-line identical to CadQuery 2.7.0 shapes.extrude(), with History extraction
from the BRepPrimAPI_MakePrism builder after Build().

Verified (OCP 7.8.1.1):
- BRepPrimAPI_MakePrism has Generated()/Modified()/FirstShape()/LastShape()
- BUT does NOT have History() method (unlike BOPAlgo_BOP)
- Generated(profile_face) → TopTools_ListOfShape of generated faces
- TopTools_ListOfShape supports Python __iter__

CadQuery source: shapes.extrude(s, d) → _get(s, types) → BRepPrimAPI_MakePrism → Build → _compound_or_shape
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


def tracked_extrude(
    profile: Any,
    vector: tuple[float, float, float] | list[float],
    *,
    scope: TopologyCaptureScope | None = None,
) -> TrackedShapeResult:
    """Drop-in replacement for shapes.extrude() with History capture.

    Identical to CadQuery 2.7.0 shapes.extrude() line-by-line.
    History is extracted from BRepPrimAPI_MakePrism.Generated/Modified/FirstShape/LastShape.

    Args:
        profile: CadQuery Shape (Face, Wire, Edge, Vertex, or Compound thereof)
        vector: Extrusion direction and magnitude as (x, y, z) tuple
        scope: TopologyCaptureScope for this operation
    """
    results: list[Any] = []
    relations: list[EvolutionRelation] = []
    first_shape = None
    last_shape = None

    scope = scope or TopologyCaptureScope()

    for el in _get(profile, ("Vertex", "Edge", "Wire", "Face")):
        builder = BRepPrimAPI_MakePrism(el.wrapped, Vector(vector).wrapped)
        builder.Build()  # ★ single execution
        result_shape = builder.Shape()
        results.append(result_shape)

        el_type = el.ShapeType()

        # ── History extraction ──
        # BRepPrimAPI_MakePrism: Generated/Modified on sub-shapes (no History() method)
        # Wire profile → edges generate lateral faces
        # Face profile → face generates solid/shell

        if el_type == "Wire":
            # Each edge in the wire generates a lateral face
            for edge in el.Edges():
                gen_list = builder.Generated(edge.wrapped)
                if gen_list.Size() > 0:
                    relations.append(
                        EvolutionRelation(
                            relation_id=f"{scope.node_id}/extrude/gen/{len(relations)}",
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
                            relation_id=f"{scope.node_id}/extrude/mod/{len(relations)}",
                            kind=EvolutionKind.MODIFIED,
                            entity_type="edge",
                            source_role="profile_edge",
                            quality=HistoryQuality.EXACT_KERNEL,
                            old_shape_evidence=_face_evidence(edge),
                            new_shape_count=1,
                        )
                    )

        elif el_type == "Face":
            # Face generates the solid body
            gen_list = builder.Generated(el.wrapped)
            if gen_list.Size() > 0:
                relations.append(
                    EvolutionRelation(
                        relation_id=f"{scope.node_id}/extrude/gen/{len(relations)}",
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
                        relation_id=f"{scope.node_id}/extrude/mod/{len(relations)}",
                        kind=EvolutionKind.MODIFIED,
                        entity_type="face",
                        source_role="profile_face",
                        quality=HistoryQuality.EXACT_KERNEL,
                        old_shape_evidence=_face_evidence(el),
                        new_shape_count=1,
                    )
                )

        # Capture FirstShape/LastShape once (start cap / end cap)
        if first_shape is None:
            first_shape = builder.FirstShape()
        last_shape = builder.LastShape()

    result = _compound_or_shape(results)

    batch = TopologyEvolutionBatch(
        scope=scope,
        builder_kind="BRepPrimAPI_MakePrism",
        builder_options={
            "vector": tuple(float(v) for v in vector),
        },
        result_shape=result.wrapped,
        context_shape=result.wrapped,
        relations=relations,
        first_shape=first_shape,
        last_shape=last_shape,
        history_complete=True,
    )
    return TrackedShapeResult(result=result, capture_token=_stage(batch))
