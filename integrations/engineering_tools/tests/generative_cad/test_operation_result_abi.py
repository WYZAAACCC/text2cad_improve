"""P3: OperationResult ABI tests."""


class TestOperationResultABI:
    def test_operation_result_model_exists(self):
        from seekflow_engineering_tools.generative_cad.dialects.results import (
            OperationResult, OperationOutput, OperationMetric,
        )
        r = OperationResult(
            ok=True,
            outputs=[OperationOutput(name="body", handle_id="h1", value_type="solid")],
        )
        assert r.ok
        assert len(r.outputs) == 1
        assert r.outputs[0].name == "body"

    def test_operation_result_extra_forbid(self):
        from seekflow_engineering_tools.generative_cad.dialects.results import (
            OperationResult, OperationOutput,
        )
        import pytest
        with pytest.raises(Exception):
            OperationResult(
                ok=True,
                outputs=[OperationOutput(name="body", handle_id="h1", value_type="solid")],
                extra_field="should_fail",
            )

    def test_legacy_handler_adapter(self):
        from seekflow_engineering_tools.generative_cad.dialects.results import adapt_legacy_handler_result
        from seekflow_engineering_tools.generative_cad.ir.canonical import (
            CanonicalNode, CanonicalValueDecl,
        )
        node = CanonicalNode(
            id="n1", component="c1", dialect="axisymmetric",
            op="revolve_profile", op_version="1.0.0", phase="base_solid",
            outputs=[CanonicalValueDecl(name="body", type="solid", value_id="v1")],
            required=True,
        )
        result = adapt_legacy_handler_result({"body": "h1"}, node)
        assert result.ok
        assert result.outputs[0].name == "body"
        assert result.outputs[0].handle_id == "h1"
        assert result.outputs[0].value_type == "solid"

    def test_operation_spec_has_handler_kind(self):
        from seekflow_engineering_tools.generative_cad.dialects.operation import OperationSpec
        import inspect
        fields = OperationSpec.model_fields
        assert "handler_kind" in fields
        assert fields["handler_kind"].default == "v1_dict"

    def test_operation_result_defaults(self):
        from seekflow_engineering_tools.generative_cad.dialects.results import (
            OperationResult, OperationOutput,
        )
        r = OperationResult(
            outputs=[OperationOutput(name="body", handle_id="h1", value_type="solid")],
        )
        assert r.ok is True
        assert r.warnings == []
        assert r.degraded_features == []
        assert r.metrics == []

    def test_v2_handler_result_outputs_match_spec(self):
        """verify that a custom V2 handler can return OperationResult matching spec."""
        from seekflow_engineering_tools.generative_cad.dialects.results import (
            OperationResult, OperationOutput,
        )
        # Simulate a v2 handler
        result = OperationResult(
            ok=True,
            outputs=[
                OperationOutput(name="body", handle_id="h_body", value_type="solid"),
                OperationOutput(name="outer_frame", handle_id="h_frame", value_type="frame"),
            ],
            warnings=["degraded: used approximation for profile"],
            metrics=[],
        )
        assert result.ok
        assert len(result.outputs) == 2
        assert any(o.name == "body" and o.value_type == "solid" for o in result.outputs)

    def test_new_operation_result_fails_without_outputs(self):
        import pytest
        from pydantic import ValidationError
        from seekflow_engineering_tools.generative_cad.dialects.results import OperationResult
        with pytest.raises(ValidationError):
            OperationResult()
