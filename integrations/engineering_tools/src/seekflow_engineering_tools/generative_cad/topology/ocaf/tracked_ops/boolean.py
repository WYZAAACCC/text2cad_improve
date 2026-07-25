"""Tracked Boolean operations — drop-in replacements for CadQuery shapes.cut/fuse/common.

Line-by-line identical to CadQuery 2.7.0 shapes.cut() and shapes.fuse(), with
ONE addition: SetToFillHistory(True) before Perform(), and History() extraction after.

Verified (OCP 7.8.1.1):
- BOPAlgo_BOP has SetToFillHistory(True) → History() returning BRepTools_History
- BOPAlgo_BOP produces identical volume to BRepAlgoAPI_Cut
- TopTools_ListOfShape supports Python __iter__

CadQuery source references:
- shapes.cut():   BOPAlgo_BOP + BOPAlgo_CUT + _set_glue + _set_builder_options + Perform
- shapes.fuse():  BOPAlgo_BOP + BOPAlgo_FUSE + same pattern
"""

from __future__ import annotations

import uuid
from typing import Any

from cadquery.occ_impl.shapes import (
    _compound_or_shape,
    _set_glue,
    _set_builder_options,
)
from OCP.BOPAlgo import BOPAlgo_BOP, BOPAlgo_CUT, BOPAlgo_FUSE, BOPAlgo_COMMON

from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    EvolutionKind,
    EvolutionRelation,
    HistoryQuality,
    TopologyCaptureScope,
    TopologyEvolutionBatch,
    TrackedShapeResult,
)

# In-memory staging registry for PR-1 (replaced by CaptureSession in PR-2)
_staged_batches: dict[str, TopologyEvolutionBatch] = {}


def _stage(batch: TopologyEvolutionBatch) -> str:
    """Stage a batch and return a capture token. PR-1 simple in-memory version."""
    token = f"capture:{batch.scope.node_id}:{uuid.uuid4().hex[:12]}"
    _staged_batches[token] = batch
    return token


def get_staged_batch(token: str) -> TopologyEvolutionBatch | None:
    """Retrieve a previously staged batch by token."""
    return _staged_batches.get(token)


def tracked_cut(
    target: Any,
    tool: Any,
    *,
    tol: float = 0.0,
    glue: str | None = None,
    scope: TopologyCaptureScope | None = None,
) -> TrackedShapeResult:
    """Drop-in replacement for shapes.cut() with History capture.

    Identical to CadQuery 2.7.0 shapes.cut() line-by-line.
    Only addition: SetToFillHistory(True) + History() extraction.
    """
    builder = BOPAlgo_BOP()
    builder.SetOperation(BOPAlgo_CUT)
    builder.SetToFillHistory(True)  # ★ the ONLY addition to enable history
    _set_glue(builder, glue)
    _set_builder_options(builder, tol)
    builder.AddArgument(target.wrapped)
    builder.AddTool(tool.wrapped)
    builder.Perform()  # ★ single execution

    result = _compound_or_shape(builder.Shape())
    history = builder.History()  # ★ extract history

    batch = _export_bopalgo_history(
        history,
        target=target,
        tool=tool,
        result=result,
        builder_kind="BOPAlgo_BOP",
        operation="cut",
        scope=scope or TopologyCaptureScope(),
    )
    return TrackedShapeResult(result=result, capture_token=_stage(batch))


def tracked_fuse(
    left: Any,
    right: Any,
    *,
    tol: float = 0.0,
    glue: str | None = None,
    scope: TopologyCaptureScope | None = None,
) -> TrackedShapeResult:
    """Drop-in replacement for shapes.fuse() with History capture.

    Identical to CadQuery 2.7.0 shapes.fuse() line-by-line.
    """
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
        history,
        target=left,
        tool=right,
        result=result,
        builder_kind="BOPAlgo_BOP",
        operation="fuse",
        scope=scope or TopologyCaptureScope(),
    )
    return TrackedShapeResult(result=result, capture_token=_stage(batch))


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
        history,
        target=left,
        tool=right,
        result=result,
        builder_kind="BOPAlgo_BOP",
        operation="common",
        scope=scope or TopologyCaptureScope(),
    )
    return TrackedShapeResult(result=result, capture_token=_stage(batch))


# ── History extraction ──────────────────────────────────────────────────────────


def _export_bopalgo_history(
    history: Any,
    target: Any,
    tool: Any,
    result: Any,
    builder_kind: str,
    operation: str,
    scope: TopologyCaptureScope,
) -> TopologyEvolutionBatch:
    """Extract EvolutionRelations from BRepTools_History after BOPAlgo_BOP.

    Iterates each face of target and tool, queries:
      - history.Generated(face) → TopTools_ListOfShape (new faces from this face)
      - history.Modified(face) → TopTools_ListOfShape (modified version of this face)
      - history.IsRemoved(face) → bool (face no longer exists in result)

    TopTools_ListOfShape supports Python __iter__ in OCP 7.8.1.1 (verified).
    """
    relations: list[EvolutionRelation] = []

    for role_name, shape in [("target", target), ("tool", tool)]:
        for i, face in enumerate(shape.Faces()):
            fw = face.wrapped
            role = f"{role_name}_face_{i}"

            # Generated: new faces in result created from this input face
            gen_list = history.Generated(fw)
            if gen_list.Size() > 0:
                for _gen_shape in gen_list:
                    relations.append(
                        EvolutionRelation(
                            relation_id=f"{scope.node_id}/{role}/gen/{len(relations)}",
                            kind=EvolutionKind.GENERATED,
                            entity_type="face",
                            source_role=role,
                            quality=HistoryQuality.EXACT_KERNEL,
                            old_shape_evidence=_face_evidence(face),
                            new_shape_count=gen_list.Size(),
                        )
                    )

            # Modified: this input face was modified (typically 1:1)
            mod_list = history.Modified(fw)
            if mod_list.Size() > 0:
                for _mod_shape in mod_list:
                    relations.append(
                        EvolutionRelation(
                            relation_id=f"{scope.node_id}/{role}/mod/{len(relations)}",
                            kind=EvolutionKind.MODIFIED,
                            entity_type="face",
                            source_role=role,
                            quality=HistoryQuality.EXACT_KERNEL,
                            old_shape_evidence=_face_evidence(face),
                            new_shape_count=1,
                        )
                    )

            # IsRemoved: this face no longer exists in result
            if history.IsRemoved(fw):
                relations.append(
                    EvolutionRelation(
                        relation_id=f"{scope.node_id}/{role}/del/{len(relations)}",
                        kind=EvolutionKind.DELETED,
                        entity_type="face",
                        source_role=role,
                        quality=HistoryQuality.EXACT_KERNEL,
                        old_shape_evidence=_face_evidence(face),
                        new_shape_count=0,
                    )
                )

    return TopologyEvolutionBatch(
        scope=scope,
        builder_kind=builder_kind,
        builder_options={"operation": operation},
        result_shape=result.wrapped,
        context_shape=result.wrapped,
        relations=relations,
        history_complete=True,
    )


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
