"""Phase 4 tests — topology_mode='required' enforcement."""

import pytest

from seekflow_engineering_tools.generative_cad.topology.models import (
    TopologyDelta,
    TopologyRelation,
)
from seekflow_engineering_tools.generative_cad.dialects.executor import (
    _apply_topology_delta_if_present,
)
from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalNode
from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext
from seekflow_engineering_tools.generative_cad.dialects.results import OperationResult
from seekflow_engineering_tools.generative_cad.runtime.errors import GcadRuntimeError


class FakeOpSpecRequired:
    topology_mode = "required"
    topology_contract = None


class FakeOpSpecOptional:
    topology_mode = "optional"
    topology_contract = None


def _make_node():
    return CanonicalNode(
        id="n1",
        dialect="axisymmetric",
        op="revolve_profile",
        op_version="1.0.0",
        phase="base_solid",
        component="disk",
        params={},
        inputs=[],
        outputs=[],
        typed_params={},
    )


def _make_ctx():
    ctx = RuntimeContext(
        out_step="test.step",
        metadata_path="test.json",
        workspace_root=".",
    )
    return ctx


class TestTopologyDeltaRequired:
    """T-007 FIX: required mode — missing delta → build error."""

    def test_required_missing_delta_raises(self):
        """topology_mode='required' with no delta → GcadRuntimeError."""
        node = _make_node()
        ctx = _make_ctx()
        result = OperationResult(
            ok=True,
            outputs=[],
            topology_delta=None,  # MISSING
        )
        with pytest.raises(GcadRuntimeError, match="produced no topology delta"):
            _apply_topology_delta_if_present(
                node=node, result=result, ctx=ctx,
                op_spec=FakeOpSpecRequired(),
            )

    def test_required_invalid_delta_raises(self):
        """topology_mode='required' with invalid delta → GcadRuntimeError."""
        node = _make_node()
        ctx = _make_ctx()
        delta = TopologyDelta(
            node_id="n1", component_id="disk",
            history_provider="operation_semantics",
            relations=[
                TopologyRelation(
                    relation="modified",
                    source_ids=["gct2_nonexistent"],  # unknown source → ValueError
                    result_entity_keys=["gct2_key"],
                ),
            ],
        )
        result = OperationResult(
            ok=True,
            outputs=[],
            topology_delta=delta,
        )
        with pytest.raises(GcadRuntimeError, match="delta application failed"):
            _apply_topology_delta_if_present(
                node=node, result=result, ctx=ctx,
                op_spec=FakeOpSpecRequired(),
            )

    def test_required_valid_delta_succeeds(self):
        """topology_mode='required' with valid delta → success (no error)."""
        node = _make_node()
        ctx = _make_ctx()
        # Pre-register entity so delta resolves
        from seekflow_engineering_tools.generative_cad.topology.models import (
            TopologyEntityRecord,
        )
        rec = TopologyEntityRecord(
            persistent_id="gct2_valid",
            entity_type="face", component_id="disk",
            owner_body_handle_id="solid:disk:n1:body",
            producer_node_id="n1", semantic_role="test",
        )
        ctx.topology_registry.register_entity(rec)

        delta = TopologyDelta(
            node_id="n1", component_id="disk",
            history_provider="operation_semantics",
            relations=[
                TopologyRelation(
                    relation="unchanged",
                    source_ids=["gct2_valid"],
                ),
            ],
        )
        result = OperationResult(
            ok=True,
            outputs=[],
            topology_delta=delta,
        )
        # Should not raise
        _apply_topology_delta_if_present(
            node=node, result=result, ctx=ctx,
            op_spec=FakeOpSpecRequired(),
        )


class TestTopologyDeltaOptional:
    """Legacy: optional mode — missing delta is a no-op."""

    def test_optional_missing_delta_no_error(self):
        """topology_mode='optional' with no delta → no error."""
        node = _make_node()
        ctx = _make_ctx()
        result = OperationResult(
            ok=True,
            outputs=[],
            topology_delta=None,
        )
        # Should not raise
        _apply_topology_delta_if_present(
            node=node, result=result, ctx=ctx,
            op_spec=FakeOpSpecOptional(),
        )

    def test_optional_invalid_delta_is_warning(self):
        """topology_mode='optional' with invalid delta → warning, not error."""
        node = _make_node()
        ctx = _make_ctx()
        delta = TopologyDelta(
            node_id="n1", component_id="disk",
            history_provider="operation_semantics",
            relations=[
                TopologyRelation(
                    relation="modified",
                    source_ids=["gct2_nonexistent"],
                    result_entity_keys=["gct2_key"],
                ),
            ],
        )
        result = OperationResult(
            ok=True,
            outputs=[],
            topology_delta=delta,
        )
        # Should not raise — warning only
        _apply_topology_delta_if_present(
            node=node, result=result, ctx=ctx,
            op_spec=FakeOpSpecOptional(),
        )
        assert len(ctx.warnings) >= 1
        assert "Topology delta application failed" in ctx.warnings[0]
