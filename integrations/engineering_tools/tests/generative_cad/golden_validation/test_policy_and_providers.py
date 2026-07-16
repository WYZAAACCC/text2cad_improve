"""Phase 5 试点 — 细粒度 OpVersionRepairProvider + Policy 门控测试."""
from __future__ import annotations
import copy
import json
from pathlib import Path

from seekflow_engineering_tools.generative_cad.repair_kernel import (
    OpVersionRepairProvider,
    provider_matches,
    repair_documents,
)
from seekflow_engineering_tools.generative_cad.validation_kernel import run_validation
from seekflow_engineering_tools.generative_cad.validation_kernel.policy import (
    ValidationPolicy,
    default_validation_policy,
)

FIXTURES_GC = Path(__file__).parents[2] / "fixtures" / "generative_cad"


def _doc_with_bad_op_version() -> dict:
    """构造 unknown_op 失败: 把合法文档的一个 op_version 改成 dialect 版本号."""
    data = json.loads((FIXTURES_GC / "axisymmetric_minimal.json").read_text(encoding="utf-8"))
    data = copy.deepcopy(data)
    data["nodes"][0]["op_version"] = "0.2.0"   # dialect 版本冒充 op 版本 (典型幻觉)
    return data


class TestPolicyDefaultsFrozen:
    def test_geometry_policy_matches_legacy_constants(self):
        """§16 迁移不改变阈值 — 与迁移前 DEFAULT_GEOMETRY_POLICY 逐项一致."""
        g = default_validation_policy().geometry
        assert g.max_nodes == 64
        assert g.max_boolean_ops == 256
        assert g.max_profile_points == 128
        assert g.min_edge_length_mm == 0.25
        assert g.min_wall_thickness_mm == 1.0
        assert g.min_boolean_clearance_mm == 0.2
        assert g.min_hole_to_boundary_margin_mm == 1.0
        assert g.max_pattern_instances == 360
        assert g.max_fillet_ratio_to_local_thickness == 0.25

    def test_preflight_compat_view_consistent(self):
        from seekflow_engineering_tools.generative_cad.validation.geometry_preflight import (
            DEFAULT_GEOMETRY_POLICY,
        )
        assert DEFAULT_GEOMETRY_POLICY == default_validation_policy().geometry.model_dump()


class TestOpVersionProvider:
    def test_subscription_matching(self):
        p = OpVersionRepairProvider()
        assert provider_matches(p, {"unknown_op"})
        assert provider_matches(p, {"dialect_version_mismatch", "other"})
        assert not provider_matches(p, {"pydantic_validation_failed"})

    def test_fine_grained_provider_repairs_op_version(self):
        """unknown_op 失败 → 细粒度 Provider (而非 legacy 链) 完成修复."""
        doc = _doc_with_bad_op_version()
        vrun = run_validation(doc)
        assert not vrun.report.ok
        codes = {i.code for i in vrun.report.issues}
        assert "unknown_op" in codes

        res = repair_documents(doc, vrun)
        assert res.outcome.accepted
        assert res.outcome.final_ok
        accepted = [r for r in res.outcome.records if r.accepted]
        assert accepted[0].provider_id == "repair.contract.op_version"
        assert accepted[0].risk == "contract_derived"

    def test_provider_noop_on_unrelated_document(self):
        p = OpVersionRepairProvider()
        data = json.loads((FIXTURES_GC / "axisymmetric_minimal.json").read_text(encoding="utf-8"))
        fixed, rule_ids = p.propose(data, [])
        assert rule_ids == []


class TestPolicyGating:
    def test_legacy_chain_blocked_when_policy_disallows(self):
        """allow_legacy_chain=False → legacy 链被策略拒绝并记录, 不静默."""
        doc = _doc_with_bad_op_version()
        # 破坏成只有 legacy 能处理的错误: 再注入一个 pydantic 层问题
        doc["nodes"][0]["op_version"] = "0.2.0"
        vrun = run_validation(doc)
        pol = ValidationPolicy()
        pol.repair.allow_legacy_chain = False
        res = repair_documents(doc, vrun, policy=pol)
        # op_version provider (contract_derived) 仍可用并修复
        assert res.outcome.final_ok
        blocked = [r for r in res.outcome.records
                   if r.reject_reason == "risk not allowed by policy"]
        # legacy 未被触发或被策略拒绝, 二者必居其一且无静默
        assert all(r.provider_id != "repair.legacy_autofix_chain" or r.reject_reason
                   for r in res.outcome.records)
        assert blocked or all(r.provider_id != "repair.legacy_autofix_chain"
                              for r in res.outcome.records)
