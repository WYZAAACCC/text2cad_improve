"""Unit tests for LiveEvolutionRelation contract and Audit projection.

Verifies §5.1 of the v3.0 implementation guide:
  - validate() enforces shape contract per EvolutionKind
  - Audit projection contains NO Shape handles
  - PRIMITIVE/GENERATED/MODIFIED/DELETED constraints
"""

import pytest

from seekflow_engineering_tools.generative_cad.topology.ocaf.errors import (
    InvalidEvolutionRelationError,
)
from seekflow_engineering_tools.generative_cad.topology.ocaf.models import (
    EvolutionKind,
    TopologyEntityKind,
    ProofClass,
    LiveEvolutionRelation,
    LiveEvolutionBatch,
    EvolutionRelationAudit,
    TopologyCaptureScope,
    TrackedShapeResult,
    rel_to_audit,
)


class MockShape:
    """Mock TopoDS_Shape for testing (no OCP dependency)."""
    def __init__(self, name="mock"):
        self._name = name
    def IsNull(self):
        return False


class TestLiveEvolutionRelationContract:
    """validate() enforces the correct shape combinations per kind."""

    def make_rel(self, kind, old_shape=None, new_shapes=()):
        return LiveEvolutionRelation(
            relation_id="test/1",
            operation_id="op-1",
            kind=kind,
            entity_kind=TopologyEntityKind.FACE,
            source_key="face_0",
            old_shape=old_shape,
            new_shapes=new_shapes,
            proof=ProofClass.EXACT_KERNEL_HISTORY,
        )

    def test_primitive_no_old_has_new(self):
        """PRIMITIVE: old_shape=None, new_shapes >= 1."""
        rel = self.make_rel(EvolutionKind.PRIMITIVE, old_shape=None, new_shapes=(MockShape("new"),))
        rel.validate()  # should not raise

    def test_primitive_with_old_raises(self):
        """PRIMITIVE with old_shape must raise."""
        rel = self.make_rel(EvolutionKind.PRIMITIVE, old_shape=MockShape("old"), new_shapes=(MockShape("new"),))
        with pytest.raises(InvalidEvolutionRelationError):
            rel.validate()

    def test_primitive_no_new_raises(self):
        """PRIMITIVE with 0 new_shapes must raise."""
        rel = self.make_rel(EvolutionKind.PRIMITIVE, old_shape=None, new_shapes=())
        with pytest.raises(InvalidEvolutionRelationError):
            rel.validate()

    def test_generated_valid(self):
        """GENERATED: old_shape!=None, new_shapes >= 1."""
        rel = self.make_rel(EvolutionKind.GENERATED, old_shape=MockShape("old"), new_shapes=(MockShape("new"),))
        rel.validate()

    def test_generated_no_old_raises(self):
        """GENERATED without old_shape must raise."""
        rel = self.make_rel(EvolutionKind.GENERATED, old_shape=None, new_shapes=(MockShape("new"),))
        with pytest.raises(InvalidEvolutionRelationError):
            rel.validate()

    def test_generated_no_new_raises(self):
        """GENERATED with 0 new_shapes must raise."""
        rel = self.make_rel(EvolutionKind.GENERATED, old_shape=MockShape("old"), new_shapes=())
        with pytest.raises(InvalidEvolutionRelationError):
            rel.validate()

    def test_modified_valid(self):
        """MODIFIED: old_shape!=None, new_shapes >= 1."""
        rel = self.make_rel(EvolutionKind.MODIFIED, old_shape=MockShape("old"), new_shapes=(MockShape("new"),))
        rel.validate()

    def test_modified_no_old_raises(self):
        """MODIFIED without old_shape must raise."""
        rel = self.make_rel(EvolutionKind.MODIFIED, old_shape=None, new_shapes=(MockShape("new"),))
        with pytest.raises(InvalidEvolutionRelationError):
            rel.validate()

    def test_deleted_valid(self):
        """DELETED: old_shape!=None, new_shapes == 0."""
        rel = self.make_rel(EvolutionKind.DELETED, old_shape=MockShape("old"), new_shapes=())
        rel.validate()

    def test_deleted_no_old_raises(self):
        """DELETED without old_shape must raise."""
        rel = self.make_rel(EvolutionKind.DELETED, old_shape=None, new_shapes=())
        with pytest.raises(InvalidEvolutionRelationError):
            rel.validate()

    def test_deleted_with_new_raises(self):
        """DELETED with new_shapes must raise."""
        rel = self.make_rel(EvolutionKind.DELETED, old_shape=MockShape("old"), new_shapes=(MockShape("new"),))
        with pytest.raises(InvalidEvolutionRelationError):
            rel.validate()


class TestAuditProjection:
    """EvolutionRelationAudit must NOT contain TopoDS_Shape handles."""

    def test_audit_no_shape_handles(self):
        """Audit projection contains only scalar evidence."""
        old = MockShape("old_face")
        new1 = MockShape("new_face_1")
        new2 = MockShape("new_face_2")

        rel = LiveEvolutionRelation(
            relation_id="test/1",
            operation_id="op-1",
            kind=EvolutionKind.GENERATED,
            entity_kind=TopologyEntityKind.FACE,
            source_key="face_0",
            old_shape=old,
            new_shapes=(new1, new2),
            proof=ProofClass.EXACT_KERNEL_HISTORY,
        )

        audit = rel_to_audit(rel)
        assert isinstance(audit, EvolutionRelationAudit)
        # Audit evidence should be dicts (or None), not MockShape objects
        assert audit.old_evidence is None or isinstance(audit.old_evidence, dict)
        for ev in audit.new_evidence:
            assert isinstance(ev, dict)

    def test_batch_to_audit(self):
        """LiveEvolutionBatch.to_audit() produces audit records."""
        rel = LiveEvolutionRelation(
            relation_id="test/1",
            operation_id="op-1",
            kind=EvolutionKind.PRIMITIVE,
            entity_kind=TopologyEntityKind.FACE,
            source_key="primitive",
            old_shape=None,
            new_shapes=(MockShape("box"),),
            proof=ProofClass.EXACT_CONSTRUCTION,
        )
        batch = LiveEvolutionBatch(
            scope=TopologyCaptureScope(node_id="test_node"),
            builder_kind="Test",
            result_shape=MockShape("result"),
            context_shape=MockShape("result"),
            relations=[rel],
        )
        audit_list = batch.to_audit()
        assert len(audit_list) == 1
        assert audit_list[0].relation_id == "test/1"
        assert audit_list[0].proof == "exact_construction"


class TestTrackedShapeResult:
    """TrackedShapeResult holds batch directly (no capture_token)."""

    def test_no_capture_token(self):
        """TrackedShapeResult must NOT have capture_token attribute."""
        batch = LiveEvolutionBatch(scope=TopologyCaptureScope(), builder_kind="test")
        result = TrackedShapeResult(result="fake_shape", batch=batch)
        assert not hasattr(result, "capture_token")
        assert result.batch is batch
        assert result.result == "fake_shape"
