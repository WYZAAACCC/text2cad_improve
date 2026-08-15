"""Shared carry-through helpers for modification-type tracked operations.

``history_complete`` must mean: every input face is accounted for by a
Generated/Modified/Deleted relation, or it is carried through unchanged (its
TShape survives in the result). These helpers let each tracked op write the
missing carry-through MODIFIED relation and compute the honest flag.
"""

from __future__ import annotations

from typing import Any

from OCP.TopAbs import TopAbs_FACE
from OCP.TopExp import TopExp_Explorer

from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    EvolutionKind,
    LiveEvolutionRelation,
    ProofClass,
    TopologyCaptureScope,
    TopologyEntityKind,
)


def iter_faces(shape: Any) -> list[Any]:
    """Return all TopoDS_Face handles in ``shape``."""
    try:
        exp = TopExp_Explorer(shape, TopAbs_FACE)
        faces: list[Any] = []
        while exp.More():
            faces.append(exp.Current())
            exp.Next()
        return faces
    except Exception:
        return []


def find_partner_face(result_shape: Any, face: Any) -> Any | None:
    """Return a face in ``result_shape`` sharing the same TShape as ``face``."""
    try:
        for rf in iter_faces(result_shape):
            if rf.IsPartner(face) or rf.IsSame(face):
                return rf
    except Exception:
        pass
    return None


def _wrapped(face: Any) -> Any:
    return face.wrapped if hasattr(face, "wrapped") else face


def is_accounted(relations: list[LiveEvolutionRelation], face: Any) -> bool:
    """True if ``face`` is the old_shape of some existing relation."""
    target = _wrapped(face)
    for rel in relations:
        if rel.old_shape is None:
            continue
        try:
            if target.IsPartner(rel.old_shape) or target.IsSame(rel.old_shape):
                return True
        except Exception:
            continue
    return False


def all_faces_accounted(
    relations: list[LiveEvolutionRelation], input_faces: list[Any],
) -> bool:
    """True if every input face has an accounting relation."""
    return all(is_accounted(relations, face) for face in input_faces)


def carry_unchanged_faces(
    relations: list[LiveEvolutionRelation],
    scope: TopologyCaptureScope,
    result_shape: Any,
    input_faces: list[Any],
    source_prefix: str,
) -> int:
    """Write carry-through MODIFIED relations for unchanged input faces.

    Returns the number of carry-through relations added.
    """
    added = 0
    for i, face in enumerate(input_faces):
        fw = _wrapped(face)
        if is_accounted(relations, fw):
            continue
        partner = find_partner_face(result_shape, fw)
        if partner is None:
            continue
        relations.append(
            LiveEvolutionRelation(
                relation_id=f"{scope.node_id}/{source_prefix}/carry/face_{i}",
                operation_id=scope.node_id,
                kind=EvolutionKind.MODIFIED,
                entity_kind=TopologyEntityKind.FACE,
                source_key=f"face_{i}",
                old_shape=fw,
                new_shapes=(partner,),
                proof=ProofClass.EXACT_KERNEL_HISTORY,
            )
        )
        added += 1
    return added
