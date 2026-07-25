"""CaptureSession — per-revision staging for topology capture batches.

Replaces PR-1's global _staged_batches dict with session-scoped, ordered storage.
Each pipeline run can create a CaptureSession to collect history from tracked ops.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    TopologyEvolutionBatch,
    TrackedShapeResult,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.tracked_ops.boolean import (
    get_staged_batch,
)


@dataclass
class CaptureSession:
    """Collects TopologyEvolutionBatches during a single pipeline run.

    Usage:
        session = CaptureSession()
        ctx.capture_session = session
        ctx.enable_topology_capture = True
        # ... run pipeline ...
        for batch in session.iter_batches():
            print(batch.scope.node_id, len(batch.relations))
    """

    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    _batches: dict[str, TopologyEvolutionBatch] = field(default_factory=dict)
    _node_order: list[str] = field(default_factory=list)

    def stage(self, tracked_result: TrackedShapeResult) -> None:
        """Stage a tracked result's batch by its capture_token.

        Pulls the batch from PR-1's global staging (get_staged_batch) and stores
        it locally. The global staging is a temporary in-memory bridge between
        tracked_ops (which writes batches) and the session (which collects them).
        """
        token = tracked_result.capture_token
        batch = get_staged_batch(token)
        if batch is not None:
            self._batches[token] = batch
            self._node_order.append(batch.scope.node_id)

    def get_batch(self, token: str) -> TopologyEvolutionBatch | None:
        """Retrieve a batch by capture token."""
        return self._batches.get(token)

    def get_batches_for_node(self, node_id: str) -> list[TopologyEvolutionBatch]:
        """Get all batches for a specific node (may be >1 for multi-builder ops)."""
        return [b for b in self._batches.values() if b.scope.node_id == node_id]

    def iter_batches(self):
        """Iterate batches in the order they were staged (node execution order)."""
        yield from self._batches.values()

    @property
    def batch_count(self) -> int:
        """Total number of staged batches."""
        return len(self._batches)

    @property
    def total_relations(self) -> int:
        """Total EvolutionRelations across all batches."""
        return sum(len(b.relations) for b in self._batches.values())

    def clear(self) -> None:
        """Clear all staged batches."""
        self._batches.clear()
        self._node_order.clear()
