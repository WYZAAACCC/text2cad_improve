"""Kernel 对抗性测试 — 异常隔离 / 同 stage 多规则 / provider 回退与谎报拒绝."""
from __future__ import annotations
import copy
import json
from pathlib import Path

from seekflow_engineering_tools.generative_cad.repair_kernel import repair_documents
from seekflow_engineering_tools.generative_cad.repair_kernel.models import (
    RepairProviderManifest,
)
from seekflow_engineering_tools.generative_cad.repair_kernel.providers import (
    LegacyAutoFixProvider,
    OpVersionRepairProvider,
)
from seekflow_engineering_tools.generative_cad.validation.reports import ValidationReport
from seekflow_engineering_tools.generative_cad.validation_kernel import (
    RuleManifest,
    RuleRegistry,
    ValidationStage,
    run_validation,
)
from seekflow_engineering_tools.generative_cad.validation_kernel.legacy_adapter import (
    register_legacy_core_rules,
)

FIXTURES_GC = Path(__file__).parents[2] / "fixtures" / "generative_cad"


def _base() -> dict:
    return json.loads((FIXTURES_GC / "axisymmetric_minimal.json").read_text(encoding="utf-8"))


class TestRuleExceptionIsolation:
    def test_crashing_rule_recorded_not_fatal(self):
        """规则抛异常 → provider_error 记录 + {stage}_validator_exception issue, 进程不崩 (§15.3)."""
        reg = RuleRegistry()
        register_legacy_core_rules(reg)

        def bomb(_subject):
            raise RuntimeError("rule crashed deliberately")

        reg.register_rule(RuleManifest(rule_id="core.test.bomb",
                                       stage=ValidationStage.SAFETY), bomb)
        reg.freeze()
        run = run_validation(_base(), registry=reg)
        statuses = {r.rule_id: r.status for r in run.execution_records}
        assert statuses["core.test.bomb"] == "provider_error"
        assert "safety_validator_exception" in {i.code for i in run.report.issues}
        assert not run.report.ok


class TestSameStageMultiRule:
    def test_reports_merged_and_stages_run_deduped(self):
        """同 stage 多规则: report 合并 (issues 拼接, ok=and), stages_run 无重复."""
        reg = RuleRegistry()
        register_legacy_core_rules(reg)

        def extra(_subject):
            return ValidationReport.fail("safety", "extra_check_failed", "injected")

        reg.register_rule(RuleManifest(rule_id="core.test.extra_safety",
                                       stage=ValidationStage.SAFETY), extra)
        reg.freeze()
        run = run_validation(_base(), registry=reg)
        assert run.report.stages_run.count("safety") == 1
        merged = run.bundle.raw_stage_reports["safety"]
        assert merged.ok is False
        assert "extra_check_failed" in {i.code for i in merged.issues}


class TestProviderRobustness:
    def _bad_doc(self) -> dict:
        doc = copy.deepcopy(_base())
        doc["nodes"][0]["op_version"] = "0.2.0"
        return doc

    def test_crashing_provider_recorded_and_falls_back(self):
        class BombProvider:
            manifest = RepairProviderManifest(
                provider_id="repair.test.bomb",
                handles_issue_codes={"*"}, risk="contract_derived")
            last_report = None

            def propose(self, doc, issues):
                raise RuntimeError("provider crashed")

        doc = self._bad_doc()
        vrun = run_validation(doc)
        res = repair_documents(doc, vrun, providers=[
            BombProvider(), OpVersionRepairProvider(), LegacyAutoFixProvider()])
        assert res.outcome.final_ok
        bomb_rec = next(r for r in res.outcome.records if r.provider_id == "repair.test.bomb")
        assert bomb_rec.error and not bomb_rec.accepted

    def test_liar_provider_rejected_by_quality_gate(self):
        """声称修复但未改文档的 provider → 质量验收拒绝, 原文档保持."""
        class LiarProvider:
            manifest = RepairProviderManifest(
                provider_id="repair.test.liar",
                handles_issue_codes={"*"}, risk="contract_derived")
            last_report = None

            def propose(self, doc, issues):
                return copy.deepcopy(doc), ["fake_fix"]

        doc = self._bad_doc()
        vrun = run_validation(doc)
        res = repair_documents(doc, vrun, providers=[LiarProvider()])
        rec = res.outcome.records[0]
        assert not rec.accepted and rec.reject_reason
        assert res.document is doc


class TestFuzzCoreInvariants:
    def test_nan_param_rejected(self):
        doc = copy.deepcopy(_base())

        def inject_nan(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        obj[k] = float("nan")
                        return True
                    if inject_nan(v):
                        return True
            if isinstance(obj, list):
                for x in obj:
                    if inject_nan(x):
                        return True
            return False

        assert inject_nan(doc["nodes"][0]["params"])
        run = run_validation(doc)
        assert not run.report.ok
        assert run.report.stage == "params"
