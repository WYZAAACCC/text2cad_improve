"""Runtime 失败分类器合同测试 (repair_loop.md §6) — fail-closed 表驱动."""
from __future__ import annotations

import pytest

from seekflow_engineering_tools.generative_cad.repair_kernel.classifier import (
    classify_runtime_failure,
)
from seekflow_engineering_tools.generative_cad.runtime.diagnostics import (
    RuntimeIssue,
    RuntimeReport,
)


def _report(*, stage="component_execution", issues=None, health=None) -> RuntimeReport:
    return RuntimeReport(ok=False, failed_stage=stage, issues=issues or [],
                         geometry_health=health or {})


def _issue(**kw) -> RuntimeIssue:
    base = dict(stage="operation_execution", code="X", message="m")
    base.update(kw)
    return RuntimeIssue(**base)


class TestNonRepairable:
    @pytest.mark.parametrize("exc_type,expected", [
        ("AttributeError", "implementation_failure"),
        ("NameError", "implementation_failure"),
        ("TypeError", "implementation_failure"),
        ("KeyError", "implementation_failure"),
        ("ImportError", "implementation_failure"),
        ("MemoryError", "infrastructure_failure"),
        ("OSError", "infrastructure_failure"),
        ("PermissionError", "infrastructure_failure"),
        ("TimeoutError", "infrastructure_failure"),
    ])
    def test_exception_type_classes(self, exc_type, expected):
        cls = classify_runtime_failure(_report(issues=[
            _issue(code="unhandled_runtime_exception", exception_type=exc_type,
                   node_id="n1", repairability="unknown")]))
        assert not cls.repairable
        assert cls.class_code == expected

    @pytest.mark.parametrize("stage,expected", [
        ("compiler_middle_end", "implementation_failure"),
        ("artifact_consistency", "implementation_failure"),
        ("step_postcheck", "infrastructure_failure"),
    ])
    def test_non_repairable_stages(self, stage, expected):
        cls = classify_runtime_failure(_report(
            stage=stage, issues=[_issue(stage=stage, repairability="non_repairable")]))
        assert not cls.repairable
        assert cls.class_code == expected

    def test_contract_mismatch(self):
        cls = classify_runtime_failure(_report(issues=[
            _issue(code="OPERATION_OUTPUT_CONTRACT_MISMATCH", node_id="n1",
                   repairability="non_repairable")]))
        assert not cls.repairable
        assert cls.class_code == "contract_failure"

    def test_unknown_exception_is_unproven(self):
        # 未分类的裸异常绝不进 LLM (fail-closed)
        cls = classify_runtime_failure(_report(issues=[
            _issue(code="unhandled_runtime_exception", exception_type="ValueError",
                   repairability="unknown")]))
        assert not cls.repairable
        assert cls.class_code == "unproven_causality"

    def test_empty_report_is_unproven(self):
        cls = classify_runtime_failure(_report(issues=[]))
        assert not cls.repairable


class TestRepairable:
    def test_required_feature_failed_with_node(self):
        cls = classify_runtime_failure(_report(issues=[
            _issue(code="REQUIRED_FEATURE_FAILED", node_id="bore_1",
                   repairability="repairable",
                   suggested_paths=["/nodes/bore_1/params"])]))
        assert cls.repairable
        assert cls.target_node_id == "bore_1"
        assert cls.allowed_paths == ["/nodes/bore_1/params"]

    def test_suggested_paths_filtered_to_target_node(self):
        # 越权 suggested_paths (指向他人节点) 必须被过滤
        cls = classify_runtime_failure(_report(issues=[
            _issue(code="REQUIRED_GEOMETRY_UNHEALTHY", node_id="n1",
                   repairability="repairable",
                   suggested_paths=["/nodes/OTHER/params", "/nodes/n1/params/radius"])]))
        assert cls.repairable
        assert cls.allowed_paths == ["/nodes/n1/params/radius"]

    def test_unique_candidate_rule(self):
        # §6.2: 后置条件失败无节点归属 → 恰一个不健康节点才可修
        cls = classify_runtime_failure(_report(
            stage="runtime_postconditions",
            issues=[_issue(stage="runtime_postconditions",
                           code="runtime_postcondition_failed",
                           repairability="conditionally_repairable")],
            health={"n1.body": {"status": "error"}, "n2.body": {"status": "ok"}}))
        assert cls.repairable
        assert cls.target_node_id == "n1"

    def test_two_unhealthy_candidates_unproven(self):
        cls = classify_runtime_failure(_report(
            stage="geometry_postcheck",
            issues=[_issue(stage="geometry_postcheck",
                           code="final_geometry_postcheck_failed",
                           repairability="conditionally_repairable")],
            health={"n1.body": {"status": "error"}, "n2.body": {"status": "error"}}))
        assert not cls.repairable
        assert cls.class_code == "unproven_causality"

    def test_zero_candidates_unproven(self):
        cls = classify_runtime_failure(_report(
            stage="runtime_postconditions",
            issues=[_issue(stage="runtime_postconditions",
                           code="runtime_postcondition_failed",
                           repairability="conditionally_repairable")],
            health={}))
        assert not cls.repairable
