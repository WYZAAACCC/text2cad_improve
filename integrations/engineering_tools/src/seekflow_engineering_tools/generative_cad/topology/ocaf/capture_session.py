"""CaptureSession — per-revision staging for topology capture batches.

Collects LiveEvolutionBatch objects during a single pipeline run.
No global staging — batches are passed directly to stage().
Ordered storage preserves node execution order.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Iterator

from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    LiveEvolutionBatch,
    LiveEvolutionRelation,
)


@dataclass
class CaptureSession:
    """Collects LiveEvolutionBatches during a single pipeline run.

    Usage:
        session = CaptureSession()
        ctx.capture_session = session
        ctx.enable_topology_capture = True
        # ... pipeline runs, each tracked op calls session.stage(result.batch) ...
        for batch in session.iter_batches():
            for rel in batch.relations:
                rel.validate()
    """

    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    _batches: list[LiveEvolutionBatch] = field(default_factory=list)
    _node_order: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Staging
    # ------------------------------------------------------------------

    def stage(self, batch: LiveEvolutionBatch) -> None:
        """Stage a batch directly. No global token lookup.

        Batches are stored in insertion order to preserve node execution sequence.
        """
        self._batches.append(batch)
        node_id = batch.scope.node_id
        if node_id:
            self._node_order.append(node_id)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def iter_batches(self) -> Iterator[LiveEvolutionBatch]:
        """Iterate batches in staging order (node execution order)."""
        yield from self._batches

    def get_batches_for_node(self, node_id: str) -> list[LiveEvolutionBatch]:
        """Get all batches for a specific node (may be >1 for multi-builder ops)."""
        return [b for b in self._batches if b.scope.node_id == node_id]

    @property
    def batch_count(self) -> int:
        return len(self._batches)

    @property
    def total_relations(self) -> int:
        return sum(len(b.relations) for b in self._batches)

    @property
    def history_complete(self) -> bool:
        """True only if every staged batch reports complete history."""
        return all(b.history_complete for b in self._batches)

    @property
    def missing_history_phases(self) -> list[str]:
        """Collect missing_phases from batches with incomplete history."""
        missing: list[str] = []
        for b in self._batches:
            if not b.history_complete:
                missing.extend(b.missing_phases)
        return missing

    @property
    def node_order(self) -> list[str]:
        """Node IDs in the order they were staged."""
        return list(self._node_order)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Clear all staged batches. Must be called after commit/abort to prevent leaks."""
        self._batches.clear()
        self._node_order.clear()

    def validate_all(self) -> list[str]:
        """Run validate() on every relation across all batches.

        Returns a list of error messages (empty = all valid).
        """
        errors: list[str] = []
        for batch in self._batches:
            for rel in batch.relations:
                try:
                    rel.validate()
                except (AssertionError, Exception) as e:
                    errors.append(str(e))
        return errors
