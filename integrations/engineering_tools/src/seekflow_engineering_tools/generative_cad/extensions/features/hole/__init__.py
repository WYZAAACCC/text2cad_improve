"""Hole Feature Extension — 首个真实扩展 (指导书 §11, Phase 4).

原 validation/hole_semantics.py 的孔语义规则从 Core 抽出:
- Kernel/Core 不再认识 cut_hole 等具体 op (验收标准 2/3);
- 仅当文档实际含孔类 operation 时激活 (验收标准 15);
- 规则实现 (validate_hole_semantics) 本体不动, 保持行为。
"""
from __future__ import annotations

from seekflow_engineering_tools.generative_cad.validation_kernel.models import (
    ExtensionManifest,
    RuleLayer,
    RuleManifest,
    RuleSelector,
)
from seekflow_engineering_tools.generative_cad.validation_kernel.stages import ValidationStage

# 本扩展感知的孔类 operation (从原 hole_semantics.py 的识别集合迁移而来)
HOLE_OPERATIONS = frozenset({
    "cut_hole",
    "cut_hole_v2",
    "cut_hole_pattern_linear",
    "cut_hole_pattern_linear_v2",
    "drill_hole_3d",
    "cut_circular_hole_pattern",
})

MANIFEST = ExtensionManifest(
    extension_id="feature.hole",
    version="1.0.0",
    kind="feature",
    selectors=[RuleSelector(operations=set(HOLE_OPERATIONS))],
)


def build_extension(reg) -> None:
    """向 RuleRegistry 注册本扩展 (统一注册接口, Kernel 不特判内置扩展)."""
    from seekflow_engineering_tools.generative_cad.validation.hole_semantics import (
        validate_hole_semantics,
    )
    reg.register_extension(MANIFEST)
    reg.register_rule(
        RuleManifest(
            rule_id="feature.hole.semantics",
            version="1.0.0",
            provider_id=MANIFEST.extension_id,
            layer=RuleLayer.EXTENSION,
            stage=ValidationStage.HOLE_SEMANTICS,
            selector=RuleSelector(operations=set(HOLE_OPERATIONS)),
        ),
        validate_hole_semantics,
    )
