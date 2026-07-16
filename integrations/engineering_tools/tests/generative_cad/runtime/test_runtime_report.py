"""Stage B — 结构化 RuntimeReport 合同测试 (repair_loop.md §5.2/§5.3).

验证: typed exception 携带结构化 issue 且 str(exc) 兼容旧字符串;
run_canonical_gcad 各失败出口产出 runtime_report 且 error 串不变。
"""
from __future__ import annotations

import pytest

from seekflow_engineering_tools.generative_cad.runtime.diagnostics import (
    RuntimeIssue,
    RuntimeReport,
)
from seekflow_engineering_tools.generative_cad.runtime.errors import GcadRuntimeError


class _FakeNode:
    id = "n_fail"
    component = "flange"
    dialect = "axisymmetric"
    op = "cut_center_bore"
    op_version = "1.0.0"
    required = True
    degradation_policy = "fail"
    outputs = []


class _FakeCtx:
    def __init__(self):
        self.warnings = []
        self.degraded_features = []
        self.operation_metrics = []
        self.geometry_health_log = {}


class TestGcadRuntimeError:
    def test_str_equals_issue_message_and_is_runtime_error(self):
        issue = RuntimeIssue(stage="operation_execution", code="X",
                             message="boom happened")
        exc = GcadRuntimeError(issue)
        assert isinstance(exc, RuntimeError)         # 既有 except RuntimeError 兼容
        assert str(exc) == "boom happened"
        assert exc.issue is issue

    def test_required_feature_failure_raises_typed(self):
        from seekflow_engineering_tools.generative_cad.runtime.recovery import (
            handle_feature_failure,
        )
        ctx = _FakeCtx()
        with pytest.raises(RuntimeError, match="Required operation") as ei:
            handle_feature_failure(
                node=_FakeNode(), ctx=ctx, original_body=None,
                op_name="center bore", exc=ValueError("cut failed"),
            )
        exc = ei.value
        assert isinstance(exc, GcadRuntimeError)
        assert exc.issue.code == "REQUIRED_FEATURE_FAILED"
        assert exc.issue.node_id == "n_fail"
        assert exc.issue.repairability == "repairable"
        assert exc.issue.suggested_paths == ["/nodes/n_fail/params"]
        assert exc.issue.exception_type == "ValueError"

    def test_invalid_degradation_policy_conditionally_repairable(self):
        from seekflow_engineering_tools.generative_cad.runtime.recovery import (
            handle_feature_failure,
        )
        node = _FakeNode()
        node.required = False
        node.degradation_policy = "fail"
        with pytest.raises(RuntimeError) as ei:
            handle_feature_failure(node=node, ctx=_FakeCtx(), original_body=None,
                                   op_name="chamfer", reason="edge gone")
        assert ei.value.issue.code == "DEGRADATION_POLICY_INVALID"
        assert ei.value.issue.repairability == "conditionally_repairable"


class TestRunCanonicalGcadReport:
    def _canonical_minimal(self):
        """构造能通过 parse 的最小 canonical 文档 (通过真实 validation)."""
        import json
        from pathlib import Path
        from seekflow_engineering_tools.generative_cad.validation.pipeline import (
            validate_and_canonicalize_with_bundle,
        )
        fixtures = Path(__file__).parents[2] / "fixtures" / "generative_cad"
        raw = json.loads((fixtures / "axisymmetric_minimal.json").read_text(encoding="utf-8"))
        canonical, report, bundle = validate_and_canonicalize_with_bundle(raw)
        assert report.ok, [i.code for i in report.issues]
        return canonical, bundle

    def test_component_exception_produces_report(self, monkeypatch, tmp_path):
        import seekflow_engineering_tools.generative_cad.pipeline.run as run_mod

        canonical, bundle = self._canonical_minimal()

        issue = RuntimeIssue(
            stage="operation_execution", code="REQUIRED_GEOMETRY_UNHEALTHY",
            message="unhealthy", node_id="n1", operation="revolve_profile",
            repairability="repairable", suggested_paths=["/nodes/n1/params"],
        )

        def _boom(canonical, ctx):
            raise GcadRuntimeError(issue)

        monkeypatch.setattr(run_mod, "_run_components", _boom)
        rr = run_mod.run_canonical_gcad(
            canonical, out_step=tmp_path / "o.step",
            metadata_path=tmp_path / "o.metadata.json",
            validation_seed=bundle.to_metadata_dict(),
            require_full_validation_seed=False,
        )
        assert not rr.ok
        assert rr.error and "unhealthy" in rr.error       # 兼容摘要仍在
        rep = rr.runtime_report
        assert isinstance(rep, RuntimeReport)
        assert rep.failed_stage == "component_execution"
        assert rep.failing_node_id == "n1"
        assert rep.issues[0].code == "REQUIRED_GEOMETRY_UNHEALTHY"
        assert rep.sanitized_traceback

    def test_generic_exception_maps_to_unknown(self, monkeypatch, tmp_path):
        import seekflow_engineering_tools.generative_cad.pipeline.run as run_mod

        canonical, bundle = self._canonical_minimal()

        def _boom(canonical, ctx):
            raise ValueError("plain failure")

        monkeypatch.setattr(run_mod, "_run_components", _boom)
        rr = run_mod.run_canonical_gcad(
            canonical, out_step=tmp_path / "o.step",
            metadata_path=tmp_path / "o.metadata.json",
            validation_seed=bundle.to_metadata_dict(),
            require_full_validation_seed=False,
        )
        assert not rr.ok
        assert rr.error.startswith("plain failure")       # error 串格式不变
        rep = rr.runtime_report
        assert rep.issues[0].code == "unhandled_runtime_exception"
        assert rep.issues[0].exception_type == "ValueError"
        assert rep.issues[0].repairability == "unknown"

    def test_success_path_produces_ok_report(self, tmp_path):
        pytest.importorskip("cadquery")
        import seekflow_engineering_tools.generative_cad.pipeline.run as run_mod

        canonical, bundle = self._canonical_minimal()
        rr = run_mod.run_canonical_gcad(
            canonical, out_step=tmp_path / "o.step",
            metadata_path=tmp_path / "o.metadata.json",
            validation_seed=bundle.to_metadata_dict(),
            require_full_validation_seed=False,
        )
        assert rr.ok, rr.error
        assert rr.runtime_report is not None
        assert rr.runtime_report.ok
        assert rr.runtime_report.geometry_health          # 健康日志被保留
