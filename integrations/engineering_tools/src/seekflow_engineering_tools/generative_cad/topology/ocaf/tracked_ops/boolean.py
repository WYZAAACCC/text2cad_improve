"""Tracked Boolean operations — drop-in replacements for CadQuery shapes.cut/fuse/common.

Line-by-line identical to CadQuery 2.7.0 shapes.cut() and shapes.fuse(), with
ONE addition: SetToFillHistory(True) before Perform(), and History() extraction after.

Verified (OCP 7.8.1.1):
- BOPAlgo_BOP has SetToFillHistory(True) → History() returning BRepTools_History
- BOPAlgo_BOP produces identical volume to BRepAlgoAPI_Cut
- TopTools_ListOfShape supports Python __iter__

PR-2 changes:
- Removed global _staged_batches dict — batches are returned directly.
- LiveEvolutionRelation stores REAL TopoDS_Shape handles (old_shape, new_shapes).
- TrackedShapeResult holds batch directly (no capture_token).
"""

from __future__ import annotations

from typing import Any

from cadquery.occ_impl.shapes import (
    _compound_or_shape,
    _set_glue,
    _set_builder_options,
)
from OCP.BOPAlgo import BOPAlgo_BOP, BOPAlgo_CUT, BOPAlgo_FUSE, BOPAlgo_COMMON

from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    EvolutionKind,
    LiveEvolutionBatch,
    LiveEvolutionRelation,
    ProofClass,
    TopologyCaptureScope,
    TopologyEntityKind,
    TrackedShapeResult,
)


# ---------------------------------------------------------------------------
# Public API — drop-in replacements for CadQuery shapes.*
# ---------------------------------------------------------------------------


def tracked_cut(
    target: Any,
    tool: Any,
    *,
    tol: float = 0.0,
    glue: str | None = None,
    scope: TopologyCaptureScope | None = None,
) -> TrackedShapeResult:
    """Drop-in replacement for shapes.cut() with History capture."""
    builder = BOPAlgo_BOP()
    builder.SetOperation(BOPAlgo_CUT)
    builder.SetToFillHistory(True)
    _set_glue(builder, glue)
    _set_builder_options(builder, tol)
    builder.AddArgument(target.wrapped)
    builder.AddTool(tool.wrapped)
    builder.Perform()

    result = _compound_or_shape(builder.Shape())
    history = builder.History()

    batch = _export_bopalgo_history(
        history, target=target, tool=tool, result=result,
        builder_kind="BOPAlgo_BOP", operation="cut",
        scope=scope or TopologyCaptureScope(),
    )
    return TrackedShapeResult(result=result, batch=batch)


def tracked_fuse(
    left: Any,
    right: Any,
    *,
    tol: float = 0.0,
    glue: str | None = None,
    scope: TopologyCaptureScope | None = None,
) -> TrackedShapeResult:
    """Drop-in replacement for shapes.fuse() with History capture."""
    builder = BOPAlgo_BOP()
    builder.SetOperation(BOPAlgo_FUSE)
    builder.SetToFillHistory(True)
    _set_glue(builder, glue)
    _set_builder_options(builder, tol)
    builder.AddArgument(left.wrapped)
    builder.AddTool(right.wrapped)
    builder.Perform()

    result = _compound_or_shape(builder.Shape())
    history = builder.History()

    batch = _export_bopalgo_history(
        history, target=left, tool=right, result=result,
        builder_kind="BOPAlgo_BOP", operation="fuse",
        scope=scope or TopologyCaptureScope(),
    )
    return TrackedShapeResult(result=result, batch=batch)


def tracked_common(
    left: Any,
    right: Any,
    *,
    tol: float = 0.0,
    glue: str | None = None,
    scope: TopologyCaptureScope | None = None,
) -> TrackedShapeResult:
    """Drop-in replacement for shapes.intersect() with History capture."""
    builder = BOPAlgo_BOP()
    builder.SetOperation(BOPAlgo_COMMON)
    builder.SetToFillHistory(True)
    _set_glue(builder, glue)
    _set_builder_options(builder, tol)
    builder.AddArgument(left.wrapped)
    builder.AddTool(right.wrapped)
    builder.Perform()

    result = _compound_or_shape(builder.Shape())
    history = builder.History()

    batch = _export_bopalgo_history(
        history, target=left, tool=right, result=result,
        builder_kind="BOPAlgo_BOP", operation="common",
        scope=scope or TopologyCaptureScope(),
    )
    return TrackedShapeResult(result=result, batch=batch)


# ---------------------------------------------------------------------------
# History extraction
# ---------------------------------------------------------------------------


def _export_bopalgo_history(
    history: Any,
    target: Any,
    tool: Any,
    result: Any,
    builder_kind: str,
    operation: str,
    scope: TopologyCaptureScope,
) -> LiveEvolutionBatch:
    """Extract LiveEvolutionRelations from BRepTools_History after BOPAlgo_BOP.

    Iterates each face of target and tool, queries Generated/Modified/IsRemoved,
    and collects REAL TopoDS_Shape handles into LiveEvolutionRelation objects.
    """
    relations: list[LiveEvolutionRelation] = []

    for role_name, shape in [("target", target), ("tool", tool)]:
        for i, face in enumerate(shape.Faces()):
            fw = face.wrapped  # TopoDS_Shape
            source_key = f"{role_name}_face_{i}"

            # ── Generated: new faces in result created from this input face ──
            gen_list = history.Generated(fw)
            gen_shapes = tuple(gen_list)  # collect REAL shapes
            if gen_shapes:
                relations.append(
                    LiveEvolutionRelation(
                        relation_id=f"{scope.node_id}/{source_key}/gen/{len(relations)}",
                        operation_id=scope.node_id,
                        kind=EvolutionKind.GENERATED,
                        entity_kind=TopologyEntityKind.FACE,
                        source_key=source_key,
                        old_shape=fw,
                        new_shapes=gen_shapes,
                        proof=ProofClass.EXACT_KERNEL_HISTORY,
                    )
                )

            # ── Modified: this face was modified (typically 1:1) ──
            mod_list = history.Modified(fw)
            mod_shapes = tuple(mod_list)
            if mod_shapes:
                relations.append(
                    LiveEvolutionRelation(
                        relation_id=f"{scope.node_id}/{source_key}/mod/{len(relations)}",
                        operation_id=scope.node_id,
                        kind=EvolutionKind.MODIFIED,
                        entity_kind=TopologyEntityKind.FACE,
                        source_key=source_key,
                        old_shape=fw,
                        new_shapes=mod_shapes,
                        proof=ProofClass.EXACT_KERNEL_HISTORY,
                    )
                )

            # ── IsRemoved: this face no longer exists in result ──
            if history.IsRemoved(fw):
                relations.append(
                    LiveEvolutionRelation(
                        relation_id=f"{scope.node_id}/{source_key}/del/{len(relations)}",
                        operation_id=scope.node_id,
                        kind=EvolutionKind.DELETED,
                        entity_kind=TopologyEntityKind.FACE,
                        source_key=source_key,
                        old_shape=fw,
                        new_shapes=(),
                        proof=ProofClass.EXACT_KERNEL_HISTORY,
                    )
                )

    batch = LiveEvolutionBatch(
        scope=scope,
        builder_kind=builder_kind,
        result_shape=result.wrapped,
        context_shape=result.wrapped,
        relations=relations,
        history_complete=True,
    )
    return batch


# ---------------------------------------------------------------------------
# Shared helper — lightweight face evidence for audit (no live Shape dependency)
# ---------------------------------------------------------------------------


def _face_evidence(face: Any) -> dict:
    """Capture lightweight audit evidence for a face (no live Shape in model).

    Only stores scalar values — area and centroid. Safe for JSON serialization.
    """
    try:
        c = face.Center()
        return {
            "area_mm2": round(face.Area(), 4),
            "center": (round(c.x, 4), round(c.y, 4), round(c.z, 4)),
        }
    except Exception:
        return {}
