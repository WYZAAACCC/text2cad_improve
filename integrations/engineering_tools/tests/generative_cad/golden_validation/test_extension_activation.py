"""Extension Activation 测试 (指导书 §19.3) — feature.hole 首个真实扩展."""
from __future__ import annotations
import json
from pathlib import Path

from seekflow_engineering_tools.generative_cad.validation_kernel import (
    default_rule_registry,
    run_validation,
)
from seekflow_engineering_tools.generative_cad.validation_kernel.activation import (
    resolve_activation_from_document,
)

FIXTURES_GC = Path(__file__).parents[2] / "fixtures" / "generative_cad"
FIXTURES_GOLDEN = Path(__file__).parent / "fixtures"


def test_hole_extension_registered_via_unified_interface():
    reg = default_rule_registry()
    assert "feature.hole.semantics" in reg.list_rule_ids()
    # Core 中不再有 hole 规则 (验收标准 2: Core 不出现特殊 op 名)
    assert "core.legacy.hole_semantics" not in reg.list_rule_ids()


def test_hole_rules_do_not_run_on_document_without_holes():
    """无孔文档: hole 规则不运行 (stages_run 无 hole_semantics), 验证仍完整通过."""
    data = json.loads((FIXTURES_GC / "axisymmetric_minimal.json").read_text(encoding="utf-8"))
    ops = {n.get("op") for n in data.get("nodes", [])}
    from seekflow_engineering_tools.generative_cad.extensions.features.hole import HOLE_OPERATIONS
    assert not (ops & HOLE_OPERATIONS), "前提: 该 fixture 必须无孔 op"

    run = run_validation(data)
    assert run.report.ok
    assert "hole_semantics" not in run.report.stages_run
    executed = {r.rule_id for r in run.execution_records if r.status != "skipped"}
    assert "feature.hole.semantics" not in executed


def test_hole_rules_run_when_hole_operation_present():
    """含孔 op 的文档: 扩展激活, hole 规则运行."""
    data = json.loads((FIXTURES_GC / "axisymmetric_minimal.json").read_text(encoding="utf-8"))
    # 构造激活: 直接由文档派生 activation (不依赖几何成功)
    data_ops = json.loads(json.dumps(data))
    # 借 parse 后对象验证 resolver
    from seekflow_engineering_tools.generative_cad.ir.parse import parse_raw_gcad_document
    parsed = parse_raw_gcad_document(data_ops)
    assert parsed.ok
    act = resolve_activation_from_document(parsed.document)
    assert act.dialects  # 至少识别出方言
    # 手工声明含孔 activation → select 必须选中扩展规则
    from seekflow_engineering_tools.generative_cad.validation_kernel import (
        ActivationSnapshot, ValidationStage,
    )
    reg = default_rule_registry()
    rules = reg.select(ValidationStage.HOLE_SEMANTICS,
                       ActivationSnapshot(operations={"cut_hole_v2"}))
    assert [r.manifest.rule_id for r in rules] == ["feature.hole.semantics"]
    # 未命中时不选中
    rules = reg.select(ValidationStage.HOLE_SEMANTICS, ActivationSnapshot())
    assert rules == []
