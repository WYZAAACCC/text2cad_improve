"""Repair Loop Orchestrator 合同测试 (repair_loop.md §19 关键条目).

用 scripted fake runtime + spy caller 覆盖: 开关语义 (§19.1 #2-5)、
runtime repair 全流程 (#37/39/40/41/46)、非可修类别 (#42/43)、
治理停机 (#26/28/36)、审计 (#48/53)、runtime 回跳非回归 (#47)。
"""
from __future__ import annotations

import json
from pathlib import Path

from seekflow_engineering_tools.generative_cad.repair_kernel import (
    RepairLoopConfig,
    check_runtime_patch,
    run_generation_loop,
)
from seekflow_engineering_tools.generative_cad.runtime.diagnostics import (
    RuntimeIssue,
    RuntimeReport,
)
from seekflow_engineering_tools.generative_cad.runtime.results import GcadRunResult

FIXTURES_GC = Path(__file__).parent.parent / "fixtures" / "generative_cad"


def _load_valid_doc() -> dict:
    return json.loads((FIXTURES_GC / "axisymmetric_minimal.json").read_text(encoding="utf-8"))


def _node_param(doc: dict, node_id: str, key: str):
    return next(n for n in doc["nodes"] if n["id"] == node_id)["params"][key]


class SpyCaller:
    """依序返回预置 patch dict; 记录调用次数."""

    def __init__(self, returns: list[dict] | None = None):
        self._returns = list(returns or [])
        self.calls = 0

    def call_strict_tool(self, **kwargs):
        from seekflow_engineering_tools.generative_cad.llm.provider import ToolCallResult
        self.calls += 1
        args = self._returns.pop(0) if self._returns else {"give_up": True,
                                                           "changes": [], "reason": "out"}
        return ToolCallResult(tool_name="emit_repair_patch", arguments=args,
                              model="mock", provider="mock")


class FakeRuntime:
    """fail N 次 (带结构化报告) 然后成功; 记录每次收到的 canonical hash."""

    def __init__(self, reports: list[RuntimeReport | None]):
        self._reports = list(reports)   # None = 成功
        self.canonical_hashes: list[str] = []

    def __call__(self, canonical, *, out_step, metadata_path,
                 validation_seed, require_full_validation_seed):
        self.canonical_hashes.append(getattr(canonical, "canonical_hash", None)
                                     or str(id(canonical)))
        rep = self._reports.pop(0) if self._reports else None
        if rep is None:
            return GcadRunResult(ok=True, runtime_report=RuntimeReport(ok=True))
        return GcadRunResult(ok=False, error="fake runtime failure",
                             runtime_report=rep)


def _repairable_report(node_id: str = "n1") -> RuntimeReport:
    return RuntimeReport(
        ok=False, failed_stage="component_execution",
        issues=[RuntimeIssue(
            stage="operation_execution", code="REQUIRED_FEATURE_FAILED",
            message="cut failed", node_id=node_id, repairability="repairable",
            suggested_paths=[f"/nodes/{node_id}/params"])],
        failing_node_id=node_id,
    )


def _implementation_report() -> RuntimeReport:
    return RuntimeReport(
        ok=False, failed_stage="component_execution",
        issues=[RuntimeIssue(
            stage="internal_exception", code="unhandled_runtime_exception",
            message="'NoneType' has no attribute x",
            exception_type="AttributeError", repairability="unknown")],
    )


def _run(doc, *, runtime, cfg=None, val_caller=None, rt_caller=None,
         audit_dir=None):
    return run_generation_loop(
        doc,
        out_step=Path("unused.step"), metadata_path=Path("unused.metadata.json"),
        config=cfg, validation_repair_caller=val_caller,
        runtime_repair_caller=rt_caller, audit_dir=audit_dir,
        runtime_runner=runtime,
    )


class TestSwitchSemantics:
    def test_enabled_false_never_calls_llm(self):
        # §19.1 #2: enabled=False 绝不调用 Agent (确定性 autofix 照跑)
        doc = _load_valid_doc()
        doc["nodes"][0]["op_version"] = "0.2.0"   # autofix 可修
        spy = SpyCaller()
        res = _run(doc, runtime=FakeRuntime([None]),
                   cfg=RepairLoopConfig(enabled=False),
                   val_caller=spy, rt_caller=spy)
        assert spy.calls == 0
        assert res.outcome.autofix_accepted          # #5: autofix 独立于 enabled
        assert res.outcome.stop_code == "success"

    def test_no_caller_reports_repair_unavailable(self):
        # §19.1 #3/#4 + §4.1: 无 caller → repair_unavailable, 不得声称 LLM 已启用
        doc = _load_valid_doc()
        doc["nodes"][0]["params"]["profile_stations"] = []   # autofix 修不了
        res = _run(doc, runtime=FakeRuntime([None]))
        assert res.outcome.stop_code == "repair_unavailable"
        assert res.outcome.validation_llm_attempts == 0

    def test_autofix_disabled(self):
        doc = _load_valid_doc()
        doc["nodes"][0]["op_version"] = "0.2.0"
        res = _run(doc, runtime=FakeRuntime([None]),
                   cfg=RepairLoopConfig(deterministic_autofix_enabled=False))
        assert not res.outcome.autofix_accepted
        assert res.outcome.stop_code in ("validation_failed", "repair_unavailable")


class TestRuntimeRepairFlow:
    def test_repairable_failure_patched_revalidated_rerun(self, tmp_path):
        # §19.5 #37/#39/#41/#46: 修 → 完整重验证 → 新 canonical 重跑 → 成功
        doc = _load_valid_doc()
        node_id = doc["nodes"][0]["id"]
        old_stations = doc["nodes"][0]["params"]["profile_stations"]
        new_stations = json.loads(json.dumps(old_stations))
        new_stations[0]["r_mm"] = round(old_stations[0]["r_mm"] * 1.1, 3)
        rt = FakeRuntime([_repairable_report(node_id), None])
        rt_caller = SpyCaller([{
            "target_node": node_id, "target_component": None,
            "changes": [{
                "path": f"/nodes/{node_id}/params/profile_stations",
                "old_value": old_stations,
                "new_value": new_stations,
                "reason": "adjust radius to feasible value",
            }],
            "reason": "fix profile", "give_up": False,
        }])
        res = _run(doc, runtime=rt, rt_caller=rt_caller, audit_dir=tmp_path)
        assert res.outcome.stop_code == "success", res.outcome.stop_reason
        assert res.outcome.runtime_llm_attempts == 1
        # #41: 第二次 runtime 收到不同 canonical (旧 canonical 未复用)
        assert len(rt.canonical_hashes) == 2
        assert rt.canonical_hashes[0] != rt.canonical_hashes[1]
        # 修复体现在最终文档
        assert _node_param(res.document, node_id, "profile_stations")[0]["r_mm"] == \
            new_stations[0]["r_mm"]
        # #48: 审计树存在
        assert (tmp_path / "repair_summary.json").exists()
        assert list((tmp_path / "repair" / "runtime").glob("attempt_*"))

    def test_path_outside_target_node_rejected(self):
        doc = _load_valid_doc()
        node_id = doc["nodes"][0]["id"]
        rt_caller = SpyCaller([{
            "target_node": node_id, "target_component": None,
            "changes": [{"path": "/nodes/SOMEONE_ELSE/params/r_mm",
                         "old_value": 1, "new_value": 1.1, "reason": "x"}],
            "reason": "x", "give_up": False,
        }])
        res = _run(doc, runtime=FakeRuntime([_repairable_report(node_id)]),
                   rt_caller=rt_caller,
                   cfg=RepairLoopConfig(max_runtime_llm_attempts=1))
        assert res.outcome.rejected_patches
        assert "outside target node" in res.outcome.rejected_patches[0]["reason"]

    def test_implementation_failure_never_reaches_llm(self):
        # §19.5 #42/#43: 代码缺陷不进 LLM, 不消耗预算
        doc = _load_valid_doc()
        spy = SpyCaller()
        res = _run(doc, runtime=FakeRuntime([_implementation_report()]),
                   rt_caller=spy)
        assert spy.calls == 0
        assert res.outcome.stop_code == "non_repairable:implementation_failure"
        assert res.outcome.runtime_llm_attempts == 0

    def test_no_runtime_caller_stops_cleanly(self):
        doc = _load_valid_doc()
        node_id = doc["nodes"][0]["id"]
        res = _run(doc, runtime=FakeRuntime([_repairable_report(node_id)]))
        assert res.outcome.stop_code == "runtime_repair_unavailable"

    def test_give_up_stops(self):
        doc = _load_valid_doc()
        node_id = doc["nodes"][0]["id"]
        res = _run(doc, runtime=FakeRuntime([_repairable_report(node_id)]),
                   rt_caller=SpyCaller([{"give_up": True, "changes": [],
                                         "reason": "cannot prove causality"}]))
        assert res.outcome.stop_code == "give_up"


class TestRuntimePatchPolicy:
    """check_runtime_patch 单元 — §8.1 硬规则 + §10.3 数值预算 (#24/#36 相关)."""

    def _patch(self, changes):
        from seekflow_engineering_tools.generative_cad.repair.patch import RepairPatchV2
        return RepairPatchV2(changes=changes, reason="t", give_up=False)

    def _check(self, changes, **cfg_kw):
        return check_runtime_patch(
            self._patch(changes), target_node_id="n1",
            allowed_paths=["/nodes/n1/params"],
            cfg=RepairLoopConfig(**cfg_kw))

    def test_scalar_within_budget_ok(self):
        ok, why = self._check([{"path": "/nodes/n1/params/radius_mm",
                                "old_value": 4.0, "new_value": 4.5, "reason": "r"}])
        assert ok, why

    def test_scalar_over_budget_rejected(self):
        ok, why = self._check([{"path": "/nodes/n1/params/radius_mm",
                                "old_value": 4.0, "new_value": 12.0, "reason": "r"}])
        assert not ok and "exceeds budget" in why

    def test_sign_flip_rejected(self):
        ok, why = self._check([{"path": "/nodes/n1/params/offset_mm",
                                "old_value": 2.0, "new_value": -2.0, "reason": "r"}])
        assert not ok and "sign flip" in why

    def test_missing_old_value_rejected(self):
        ok, why = self._check([{"path": "/nodes/n1/params/radius_mm",
                                "old_value": None, "new_value": 4.5, "reason": "r"}])
        assert not ok and "old_value" in why

    def test_numeric_type_swap_rejected(self):
        ok, why = self._check([{"path": "/nodes/n1/params/radius_mm",
                                "old_value": 4.0, "new_value": "big", "reason": "r"}])
        assert not ok and "swap" in why

    def test_too_many_changes_rejected(self):
        ch = [{"path": f"/nodes/n1/params/p{i}", "old_value": 1.0,
               "new_value": 1.1, "reason": "r"} for i in range(5)]
        ok, why = self._check(ch)
        assert not ok and "too many changes" in why

    def test_foreign_node_path_rejected(self):
        ok, why = self._check([{"path": "/nodes/OTHER/params/radius_mm",
                                "old_value": 4.0, "new_value": 4.5, "reason": "r"}])
        assert not ok and "outside target node" in why


class TestParity:
    def test_no_caller_parity_with_direct_kernel(self):
        # 无 caller 的 orchestrator ≡ 直接 run_validation + repair_documents
        from seekflow_engineering_tools.generative_cad.validation_kernel import (
            run_validation,
        )
        from seekflow_engineering_tools.generative_cad.repair_kernel import (
            repair_documents,
        )
        fixtures = Path(__file__).parent / "golden_validation" / "fixtures"
        raw = json.loads((fixtures / "79d7fc889a7e4d27" / "llm_raw.json")
                         .read_text(encoding="utf-8"))

        vrun = run_validation(raw)
        direct = repair_documents(raw, vrun)

        res = _run(json.loads(json.dumps(raw)), runtime=FakeRuntime([None]))
        assert res.vrun.report.ok == direct.run.report.ok
        assert res.outcome.autofix_accepted == direct.outcome.accepted
        if direct.run.report.ok:
            assert res.outcome.stop_code == "success"
