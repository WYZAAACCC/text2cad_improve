"""validation_kernel 合同测试 — registry 治理 (§7.1) 与 executor 等价性补充."""
from __future__ import annotations
import pytest

from seekflow_engineering_tools.generative_cad.validation.reports import ValidationReport
from seekflow_engineering_tools.generative_cad.validation_kernel import (
    ActivationSnapshot,
    RuleLayer,
    RuleManifest,
    RuleRegistry,
    RuleRegistryError,
    RuleSelector,
    ValidationStage,
    default_rule_registry,
    stage_rank,
)


def _ok_rule(_subject):
    return ValidationReport.ok_report("structure")


def _manifest(rule_id: str, **kw) -> RuleManifest:
    kw.setdefault("stage", ValidationStage.STRUCTURE)
    return RuleManifest(rule_id=rule_id, **kw)


class TestRegistryGovernance:
    def test_duplicate_rule_id_rejected(self):
        reg = RuleRegistry()
        reg.register_rule(_manifest("core.x"), _ok_rule)
        with pytest.raises(RuleRegistryError, match="duplicate"):
            reg.register_rule(_manifest("core.x"), _ok_rule)

    def test_ordering_cycle_rejected_at_freeze(self):
        reg = RuleRegistry()
        reg.register_rule(_manifest("a", before=["b"]), _ok_rule)
        reg.register_rule(_manifest("b", before=["a"]), _ok_rule)
        with pytest.raises(RuleRegistryError, match="cycle"):
            reg.freeze()

    def test_frozen_registry_rejects_registration(self):
        reg = RuleRegistry()
        reg.freeze()
        with pytest.raises(RuleRegistryError, match="frozen"):
            reg.register_rule(_manifest("core.x"), _ok_rule)

    def test_core_rules_always_selected_extension_by_selector(self):
        reg = RuleRegistry()
        reg.register_rule(_manifest("core.x"), _ok_rule)
        reg.register_rule(
            _manifest("ext.hole", layer=RuleLayer.EXTENSION,
                      selector=RuleSelector(operations={"cut_hole"})),
            _ok_rule)
        reg.freeze()
        # 未命中 selector: 只有 Core
        ids = [r.manifest.rule_id for r in reg.select(ValidationStage.STRUCTURE)]
        assert ids == ["core.x"]
        # 命中 operation: extension 加载
        act = ActivationSnapshot(operations={"cut_hole"})
        ids = [r.manifest.rule_id for r in reg.select(ValidationStage.STRUCTURE, act)]
        assert ids == ["core.x", "ext.hole"]


class TestDefaultRegistry:
    def test_covers_all_legacy_stages(self):
        reg = default_rule_registry()
        ids = reg.list_rule_ids()
        for stage in ("structure", "root_terminal", "registry", "params", "ownership",
                      "graph", "typecheck", "phase", "composition",
                      "safety", "dialect_semantics", "geometry_preflight"):
            assert f"core.legacy.{stage}" in ids
        # Phase 4: hole 规则不再属于 Core, 由 feature.hole 扩展提供
        assert "core.legacy.hole_semantics" not in ids
        assert "feature.hole.semantics" in ids

    def test_stage_rank_single_source(self):
        """governor STAGE_RANK 的迁移目标: 顺序只在 stages.py 定义一次."""
        assert stage_rank("structure") == 0
        assert stage_rank("canonicalize") > stage_rank("safety")
        assert stage_rank("geometry_preflight") > stage_rank("dialect_semantics")
        assert stage_rank("nonexistent_stage") == -1
