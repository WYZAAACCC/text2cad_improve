"""Unit tests for CaptureSession — staging, ordering, clear, and leak prevention.

Verifies §13 PR-2验收项:
  - batch 顺序稳定
  - 多 pipeline 并发不串数据（独立 session）
  - clear 后无泄漏
"""

from seekflow_engineering_tools.generative_cad.topology.ocaf.capture_session import (
    CaptureSession,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    EvolutionKind,
    TopologyEntityKind,
    ProofClass,
    TopologyCaptureScope,
    LiveEvolutionBatch,
    LiveEvolutionRelation,
)


def make_batch(node_id: str, relation_count: int = 1) -> LiveEvolutionBatch:
    """Create a minimal LiveEvolutionBatch for testing."""
    scope = TopologyCaptureScope(node_id=node_id)
    relations = [
        LiveEvolutionRelation(
            relation_id=f"{node_id}/r{i}",
            operation_id=node_id,
            kind=EvolutionKind.PRIMITIVE,
            entity_kind=TopologyEntityKind.FACE,
            source_key=f"face_{i}",
            old_shape=None,
            new_shapes=("shape",),
            proof=ProofClass.EXACT_CONSTRUCTION,
        )
        for i in range(relation_count)
    ]
    return LiveEvolutionBatch(
        scope=scope,
        builder_kind="Test",
        relations=relations,
        history_complete=True,
    )


class TestCaptureSessionBasic:
    """Basic staging and query."""

    def test_stage_accepts_live_batch(self):
        """stage() accepts LiveEvolutionBatch directly (no token)."""
        session = CaptureSession()
        batch = make_batch("node_A")
        session.stage(batch)
        assert session.batch_count == 1

    def test_batch_count_accurate(self):
        """batch_count matches staged count."""
        session = CaptureSession()
        session.stage(make_batch("A"))
        session.stage(make_batch("B"))
        session.stage(make_batch("C"))
        assert session.batch_count == 3

    def test_total_relations(self):
        """total_relations sums across all batches."""
        session = CaptureSession()
        session.stage(make_batch("A", relation_count=2))
        session.stage(make_batch("B", relation_count=3))
        assert session.total_relations == 5

    def test_get_batches_for_node(self):
        """get_batches_for_node filters by node_id."""
        session = CaptureSession()
        session.stage(make_batch("node_X"))
        session.stage(make_batch("node_Y"))
        session.stage(make_batch("node_X"))
        assert len(session.get_batches_for_node("node_X")) == 2
        assert len(session.get_batches_for_node("node_Y")) == 1
        assert len(session.get_batches_for_node("nonexistent")) == 0


class TestCaptureSessionOrdering:
    """Batches must be retrievable in staging order."""

    def test_iter_batches_preserves_order(self):
        """iter_batches() returns batches in insertion order."""
        session = CaptureSession()
        ids = ["first", "second", "third"]
        for nid in ids:
            session.stage(make_batch(nid))

        result_ids = [b.scope.node_id for b in session.iter_batches()]
        assert result_ids == ids

    def test_node_order_tracks_sequence(self):
        """node_order property reflects insertion sequence."""
        session = CaptureSession()
        session.stage(make_batch("A"))
        session.stage(make_batch("B"))
        session.stage(make_batch("C"))
        assert session.node_order == ["A", "B", "C"]

    def test_empty_node_order(self):
        """node_order skips empty node_ids."""
        session = CaptureSession()
        batch = LiveEvolutionBatch(
            scope=TopologyCaptureScope(node_id=""),  # empty
            builder_kind="Test",
        )
        session.stage(batch)
        assert session.node_order == []


class TestCaptureSessionClear:
    """clear() must prevent leaks."""

    def test_clear_removes_all_batches(self):
        """After clear(), everything is empty."""
        session = CaptureSession()
        session.stage(make_batch("A"))
        session.stage(make_batch("B"))
        session.clear()

        assert session.batch_count == 0
        assert session.total_relations == 0
        assert list(session.iter_batches()) == []
        assert session.node_order == []

    def test_no_leak_after_clear(self):
        """clear() followed by re-staging produces correct counts."""
        session = CaptureSession()
        session.stage(make_batch("A"))
        session.clear()
        session.stage(make_batch("B"))
        assert session.batch_count == 1
        assert session.node_order == ["B"]


class TestCaptureSessionIsolation:
    """Independent sessions must not share data."""

    def test_sessions_are_isolated(self):
        """Two sessions do not share batches."""
        s1 = CaptureSession()
        s2 = CaptureSession()

        s1.stage(make_batch("A"))
        s2.stage(make_batch("B"))

        assert s1.batch_count == 1
        assert s2.batch_count == 1
        assert list(s1.iter_batches())[0].scope.node_id == "A"
        assert list(s2.iter_batches())[0].scope.node_id == "B"


class TestValidateAll:
    """validate_all() checks all relations across all batches."""

    def test_all_valid_returns_empty(self):
        """All valid relations → empty error list."""
        session = CaptureSession()
        session.stage(make_batch("ok", relation_count=2))
        errors = session.validate_all()
        assert errors == []

    def test_invalid_relation_caught(self):
        """Invalid relation (DELETED with new_shapes) → reported."""
        scope = TopologyCaptureScope(node_id="bad")
        bad_rel = LiveEvolutionRelation(
            relation_id="bad/1",
            operation_id="bad",
            kind=EvolutionKind.DELETED,
            entity_kind=TopologyEntityKind.FACE,
            source_key="face_0",
            old_shape="shape",
            new_shapes=("should_not_be_here",),  # DELETED must have 0 new_shapes
            proof=ProofClass.EXACT_KERNEL_HISTORY,
        )
        batch = LiveEvolutionBatch(
            scope=scope, builder_kind="Test", relations=[bad_rel],
        )
        session = CaptureSession()
        session.stage(batch)
        errors = session.validate_all()
        assert len(errors) == 1
        assert "DELETED" in errors[0]
