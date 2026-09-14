"""Shared carry-through helpers for modification-type tracked operations.

``history_complete`` must mean: every input face is accounted for by a
Generated/Modified/Deleted relation, or it is carried through unchanged (its
TShape survives in the result). These helpers let each tracked op write the
missing carry-through MODIFIED relation and compute the honest flag.
"""

from __future__ import annotations

from typing import Any

from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
from OCP.TopExp import TopExp_Explorer
from OCP.TopTools import TopTools_IndexedMapOfShape

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


class ShapeIndex:
    """Exact TopoDS_Shape lookup using OCCT's native shape map.

    ``IsSame`` is used by ``TopTools_IndexedMapOfShape`` and is the same
    identity relation used for persistent topology matching.  Building the
    index once replaces repeated O(N) partner scans with O(1) lookups.
    """

    def __init__(self, shapes=()):
        self._map = TopTools_IndexedMapOfShape()
        self._shapes: list[Any] = []
        for shape in shapes:
            self.add(shape)

    @staticmethod
    def _unwrap(shape: Any) -> Any:
        return shape.wrapped if hasattr(shape, "wrapped") else shape

    def add(self, shape: Any) -> None:
        shape = self._unwrap(shape)
        if shape is None:
            return
        try:
            if not self._map.Contains(shape):
                self._map.Add(shape)
                self._shapes.append(shape)
        except Exception:
            return

    def contains(self, shape: Any) -> bool:
        shape = self._unwrap(shape)
        if shape is None:
            return False
        try:
            return bool(self._map.Contains(shape))
        except Exception:
            return False

    def find(self, shape: Any) -> Any | None:
        shape = self._unwrap(shape)
        if shape is None:
            return None
        try:
            if not self._map.Contains(shape):
                return None
            return self._shapes[self._map.FindIndex(shape) - 1]
        except Exception:
            return None

    def __len__(self) -> int:
        return len(self._shapes)


def find_partner_face(result_shape: Any, face: Any) -> Any | None:
    """Return a face in ``result_shape`` sharing the same TShape as ``face``."""
    try:
        for rf in iter_faces(result_shape):
            if rf.IsPartner(face) or rf.IsSame(face):
                return rf
    except Exception:
        pass
    return None


def iter_edges(shape: Any) -> list[Any]:
    """Return all TopoDS_Edge handles in ``shape``."""
    try:
        exp = TopExp_Explorer(shape, TopAbs_EDGE)
        edges: list[Any] = []
        while exp.More():
            edges.append(exp.Current())
            exp.Next()
        return edges
    except Exception:
        return []


def find_partner_edge(result_shape: Any, edge: Any) -> Any | None:
    """Return an edge in ``result_shape`` sharing the same TShape as ``edge``."""
    try:
        for re in iter_edges(result_shape):
            if re.IsPartner(edge) or re.IsSame(edge):
                return re
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
    relation_index = ShapeIndex(
        rel.old_shape for rel in relations if rel.old_shape is not None
    )
    return all(relation_index.contains(face) for face in input_faces)


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
    relation_index = ShapeIndex(
        rel.old_shape for rel in relations if rel.old_shape is not None
    )
    result_index = ShapeIndex(iter_faces(result_shape))
    for i, face in enumerate(input_faces):
        fw = _wrapped(face)
        if relation_index.contains(fw):
            continue
        partner = result_index.find(fw)
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
        relation_index.add(fw)
        added += 1
    return added
