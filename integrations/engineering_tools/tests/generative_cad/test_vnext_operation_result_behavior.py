"""M1: OperationResult ABI behavior tests — runtime output validation."""

import pytest


class TestOperationResultBehavior:
    """Behavior tests for execute_operation and OperationResult ABI."""

    @staticmethod
    def _canonical_node(**kw):
        from seekflow_engineering_tools.generative_cad.ir.canonical import (
            CanonicalNode, CanonicalValueDecl,
        )
        defaults = dict(
            id="n1", component="c1", dialect="axisymmetric",
            op="test_op", op_version="1.0.0", phase="base_solid",
            outputs=[CanonicalValueDecl(name="body", type="solid", value_id="v1")],
            required=True,
        )
        defaults.update(kw)
        return CanonicalNode(**defaults)

    @staticmethod
    def _runtime_context(tmp_path):
        from pathlib import Path
        from seekflow_engineering_tools.generative_cad.runtime.context import RuntimeContext
        return RuntimeContext(
            out_step=tmp_path / "out.step",
            metadata_path=tmp_path / "out.metadata.json",
            workspace_root=tmp_path,
        )

    @staticmethod
    def _fake_op_spec(handler, handler_kind="v1_dict"):
        from seekflow_engineering_tools.generative_cad.dialects.operation import OperationSpec
        from pydantic import BaseModel

        class FakeParams(BaseModel):
            pass

        return OperationSpec(
            dialect="axisymmetric", op="test_op", op_version="1.0.0",
            phase="base_solid",
            input_types=[], output_types=["solid"],
            params_model=FakeParams, effects=["creates_solid"],
            handler=handler, handler_kind=handler_kind,
        )

    def test_runtime_output_must_match_declared_outputs(self, tmp_path):
        """Handler returning extra output name fails."""
        from seekflow_engineering_tools.generative_cad.dialects.executor import execute_operation
        from seekflow_engineering_tools.generative_cad.runtime.handles import SolidHandle

        node = self._canonical_node()
        ctx = self._runtime_context(tmp_path)
        sid = "solid:c1:n1:body"
        ctx.object_store.put_solid(SolidHandle(id=sid, type="solid"), object())
        ctx.bind_node_output(node.id, "body", sid)

        def bad_handler(n, c):
            return {"body": sid, "extra_output": "some_hid"}

        op_spec = self._fake_op_spec(bad_handler)
        with pytest.raises(RuntimeError, match="undeclared"):
            execute_operation(node=node, op_spec=op_spec, ctx=ctx)

    def test_operation_result_output_type_mismatch_fails(self, tmp_path):
        """Handler returning wrong output type fails."""
        from seekflow_engineering_tools.generative_cad.dialects.executor import execute_operation
        from seekflow_engineering_tools.generative_cad.dialects.results import (
            OperationResult, OperationOutput,
        )
        from seekflow_engineering_tools.generative_cad.runtime.handles import SolidHandle

        node = self._canonical_node()
        ctx = self._runtime_context(tmp_path)
        sid = "solid:c1:n1:body"
        ctx.object_store.put_solid(SolidHandle(id=sid, type="solid"), object())

        def bad_v2_handler(n, c):
            return OperationResult(
                ok=True,
                outputs=[OperationOutput(name="body", handle_id=sid, value_type="frame")],
            )

        op_spec = self._fake_op_spec(bad_v2_handler, handler_kind="v2_result")
        with pytest.raises(RuntimeError, match="returned type"):
            execute_operation(node=node, op_spec=op_spec, ctx=ctx)

    def test_operation_result_handle_type_mismatch_fails(self, tmp_path):
        """Handle value_type mismatch fails."""
        from seekflow_engineering_tools.generative_cad.dialects.executor import execute_operation
        from seekflow_engineering_tools.generative_cad.dialects.results import (
            OperationResult, OperationOutput,
        )
        from seekflow_engineering_tools.generative_cad.runtime.handles import FrameHandle

        node = self._canonical_node()
        ctx = self._runtime_context(tmp_path)
        fid = "frame:c1:n1:f1"
        ctx.object_store.put_frame(FrameHandle(id=fid, type="frame"))

        def bad_v2_handler(n, c):
            return OperationResult(
                ok=True,
                outputs=[OperationOutput(name="body", handle_id=fid, value_type="solid")],
            )

        op_spec = self._fake_op_spec(bad_v2_handler, handler_kind="v2_result")
        with pytest.raises(RuntimeError, match="Handle.*has type"):
            execute_operation(node=node, op_spec=op_spec, ctx=ctx)

    def test_operation_result_missing_handle_fails(self, tmp_path):
        """Non-existent handle_id fails."""
        from seekflow_engineering_tools.generative_cad.dialects.executor import execute_operation
        from seekflow_engineering_tools.generative_cad.dialects.results import (
            OperationResult, OperationOutput,
        )

        node = self._canonical_node()
        ctx = self._runtime_context(tmp_path)

        def bad_v2_handler(n, c):
            return OperationResult(
                ok=True,
                outputs=[OperationOutput(name="body", handle_id="nonexistent_hid", value_type="solid")],
            )

        op_spec = self._fake_op_spec(bad_v2_handler, handler_kind="v2_result")
        with pytest.raises((RuntimeError, KeyError), match="not found"):
            execute_operation(node=node, op_spec=op_spec, ctx=ctx)

    def test_v1_dict_adapter_allowed_for_builtin_ops(self, tmp_path):
        """Legacy dict handler continues working through adapter.

        Uses required=False to avoid Phase 2 geometry health enforcement
        on the plain object() mock solid.
        """
        from seekflow_engineering_tools.generative_cad.dialects.executor import execute_operation
        from seekflow_engineering_tools.generative_cad.runtime.handles import SolidHandle

        node = self._canonical_node(required=False, degradation_policy="may_skip_with_warning")
        ctx = self._runtime_context(tmp_path)
        sid = "solid:c1:n1:body"
        ctx.object_store.put_solid(SolidHandle(id=sid, type="solid"), object())

        def legacy_handler(n, c):
            return {"body": sid}

        op_spec = self._fake_op_spec(legacy_handler, handler_kind="v1_dict")
        result = execute_operation(node=node, op_spec=op_spec, ctx=ctx)
        assert result.node_id == "n1"
        assert result.outputs == {"body": sid}

    def test_v2_result_metrics_warnings_propagate(self, tmp_path):
        """OperationResult metrics, warnings, degraded_features flow into ctx.

        Uses required=False to avoid Phase 2 geometry health enforcement
        on the plain object() mock solid.
        """
        from seekflow_engineering_tools.generative_cad.dialects.executor import execute_operation
        from seekflow_engineering_tools.generative_cad.dialects.results import (
            OperationResult, OperationOutput, OperationMetric,
        )
        from seekflow_engineering_tools.generative_cad.runtime.handles import SolidHandle

        node = self._canonical_node(required=False, degradation_policy="may_skip_with_warning")
        ctx = self._runtime_context(tmp_path)
        sid = "solid:c1:n1:body"
        ctx.object_store.put_solid(SolidHandle(id=sid, type="solid"), object())

        def v2_handler(n, c):
            return OperationResult(
                ok=True,
                outputs=[OperationOutput(name="body", handle_id=sid, value_type="solid")],
                warnings=["test_warning"],
                degraded_features=[{"node_id": "n1", "reason": "test"}],
                metrics=[OperationMetric(node_id="n1", op="test_op", elapsed_ms=42.0)],
            )

        op_spec = self._fake_op_spec(v2_handler, handler_kind="v2_result")
        execute_operation(node=node, op_spec=op_spec, ctx=ctx)
        assert "test_warning" in ctx.warnings
        assert any(d.get("reason") == "test" for d in ctx.degraded_features)
        assert any(m.get("elapsed_ms") == 42.0 for m in ctx.operation_metrics)

    def test_executor_rejects_ok_false(self, tmp_path):
        """OperationResult with ok=False raises."""
        from seekflow_engineering_tools.generative_cad.dialects.executor import execute_operation
        from seekflow_engineering_tools.generative_cad.dialects.results import (
            OperationResult, OperationOutput,
        )

        node = self._canonical_node()
        ctx = self._runtime_context(tmp_path)

        def fail_handler(n, c):
            return OperationResult(ok=False, outputs=[])

        op_spec = self._fake_op_spec(fail_handler, handler_kind="v2_result")
        with pytest.raises(RuntimeError, match="ok=False"):
            execute_operation(node=node, op_spec=op_spec, ctx=ctx)
