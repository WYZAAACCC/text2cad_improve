"""Repair Kernel 合同测试 (指导书 §19.2) — 质量验收 / 原子回滚 / 异常记录."""
from __future__ import annotations
import json
from pathlib import Path

from seekflow_engineering_tools.generative_cad.repair_kernel import (
    QualityVector,
    is_strict_improvement,
    repair_documents,
)
from seekflow_engineering_tools.generative_cad.validation_kernel import run_validation

FIXTURES = Path(__file__).parent / "fixtures"


class TestQualityVector:
    def test_lexicographic_ordering(self):
        ok = QualityVector(ok=True, error_count=0, warning_count=0)
        e1 = QualityVector(ok=False, error_count=1, warning_count=0)
        e2 = QualityVector(ok=False, error_count=2, warning_count=0)
        e1w = QualityVector(ok=False, error_count=1, warning_count=5)
        assert is_strict_improvement(e2, e1)
        assert is_strict_improvement(e1, ok)
        assert is_strict_improvement(e1w, e1)
        assert not is_strict_improvement(e1, e1)      # 无变化 ≠ 改善
        assert not is_strict_improvement(e1, e2)      # 恶化


class TestRepairEngineOnGolden:
    def _run(self, case: str):
        raw = json.loads((FIXTURES / case / "llm_raw.json").read_text(encoding="utf-8"))
        vrun = run_validation(raw)
        assert not vrun.report.ok
        return raw, vrun, repair_documents(raw, vrun)

    def test_accepts_repair_that_reaches_ok(self):
        # 79d7fc: 旧行为 autofix 后 revalidate.ok=True → engine 必须接受
        raw, vrun, res = self._run("79d7fc889a7e4d27")
        assert res.outcome.accepted
        assert res.outcome.final_ok
        assert res.run.report.ok
        assert res.document is not raw                # 候选是新对象
        accepted = [r for r in res.outcome.records if r.accepted]
        assert accepted, "必须有被接受的修复记录"
        rec = accepted[0]
        assert rec.error is None
        assert rec.triggered_by_issue_codes            # 由具体 Issue 触发
        assert rec.applied_rule_ids
        # 未接受的前置尝试 (如 Sanitize no-op) 也必须留有记录, 不静默
        for r in res.outcome.records:
            assert r.accepted or r.reject_reason or r.error

    def test_atomic_reject_keeps_original_document(self):
        # 19ff38: 修复后 revalidate 仍失败 → 只有质量严格改善才接受
        raw, vrun, res = self._run("19ff38e58d3f48ee")
        assert not res.outcome.final_ok
        rec = res.outcome.records[0]
        if not rec.accepted:
            # 拒绝 → 原子回滚: 文档与验证结果保持原始
            assert res.document is raw
            assert res.run is vrun
            assert rec.reject_reason
        else:
            # 接受 → 质量必须严格改善
            assert rec.quality_after.key() < rec.quality_before.key()

    def test_no_repair_when_validation_ok(self):
        raw = json.loads((FIXTURES / "79d7fc889a7e4d27" / "llm_raw.json").read_text(encoding="utf-8"))
        vrun = run_validation(raw)
        fixed_run = repair_documents(raw, vrun) if not vrun.report.ok else None
        assert fixed_run is not None
        ok_doc = fixed_run.document
        ok_run = run_validation(ok_doc)
        res = repair_documents(ok_doc, ok_run)
        assert res.outcome.attempts == 0              # ok 文档不触发任何修复
        assert res.outcome.final_ok
