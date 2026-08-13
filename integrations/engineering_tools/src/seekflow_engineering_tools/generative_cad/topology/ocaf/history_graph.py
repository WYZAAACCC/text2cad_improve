"""HistoryGraph + HistoryComposer — compose multi-stage exact history.

Implements v6.0 §10.2: combine per-stage evolution relations into an
``original semantic source -> final output entity set`` mapping, while keeping
the phase-level relations intact for audit.

Matching is done with ``TopoDS_Shape.IsPartner()`` (same TShape, orientation
insensitive) so composition never depends on face indices or enumeration order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    EvolutionKind,
    ProofClass,
)


@dataclass(frozen=True)
class HistoryEdge:
    """One directed evolution edge: old_shape -> new_shapes."""

    old_shape: Any
    new_shapes: tuple[Any, ...]
    kind: EvolutionKind
    source_key: str
    proof: ProofClass


@dataclass
class HistoryGraph:
    """Directed graph of evolution relations across all stages of one op."""

    edges: list[HistoryEdge] = field(default_factory=list)

    @classmethod
    def from_relations(cls, relations) -> HistoryGraph:
        """Build a graph from LiveEvolutionRelation objects."""
        edges = [
            HistoryEdge(
                old_shape=r.old_shape,
                new_shapes=tuple(r.new_shapes),
                kind=r.kind,
                source_key=r.source_key,
                proof=r.proof,
            )
            for r in relations
            if r.old_shape is not None
        ]
        return cls(edges)

    def successors(
        self,
        shape: Any,
        *,
        follow_kinds: tuple[EvolutionKind, ...] | None = None,
        follow_tokens: tuple[str, ...] | None = None,
    ) -> list[Any]:
        """Return target shapes reachable from ``shape`` via matching edges."""
        out: list[Any] = []
        for e in self.edges:
            if e.old_shape is None or not _same_topology(shape, e.old_shape):
                continue
            if follow_kinds is not None and e.kind not in follow_kinds:
                continue
            if follow_tokens is not None and not any(
                tok in e.source_key for tok in follow_tokens
            ):
                continue
            out.extend(e.new_shapes)
        return out


@dataclass
class HistoryComposer:
    """Compose a graph into original-source -> final-output entity sets."""

    def compose(
        self,
        graph: HistoryGraph,
        source_shapes: list[Any],
        *,
        follow_kinds: tuple[EvolutionKind, ...] = (
            EvolutionKind.GENERATED,
            EvolutionKind.MODIFIED,
        ),
        follow_tokens: tuple[str, ...] | None = None,
    ) -> list[Any]:
        """Trace each source shape forward to its terminal output shapes.

        A shape with no matching outgoing edge (under the given kinds/tokens)
        is terminal and returned. The result is de-duplicated by topology.
        """
        finals: list[Any] = []
        for src in source_shapes:
            finals.extend(self._trace(graph, src, follow_kinds, follow_tokens))
        return _dedupe(finals)

    @staticmethod
    def _trace(graph, src, follow_kinds, follow_tokens) -> list[Any]:
        frontier = [src]
        final: list[Any] = []
        visited: set[int] = set()
        while frontier:
            cur = frontier.pop(0)
            if id(cur) in visited:
                continue
            visited.add(id(cur))
            succ = graph.successors(
                cur, follow_kinds=follow_kinds, follow_tokens=follow_tokens,
            )
            if succ:
                frontier.extend(succ)
            else:
                final.append(cur)
        return final


def _same_topology(a: Any, b: Any) -> bool:
    try:
        return a.IsPartner(b)
    except Exception:
        return False


def _dedupe(shapes: list[Any]) -> list[Any]:
    out: list[Any] = []
    for s in shapes:
        if not any(_same_topology(s, o) for o in out):
            out.append(s)
    return out
