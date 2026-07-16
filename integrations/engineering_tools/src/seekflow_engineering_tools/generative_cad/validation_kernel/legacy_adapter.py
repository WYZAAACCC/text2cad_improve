"""LegacyRuleAdapter — 把现有 validation/ 下的 validator 包装为 Kernel 规则 (§17 Phase 1).

行为冻结: validator 函数本体不动, 仅加合同外壳。
Phase 4: hole_semantics 已迁出 Core → extensions/features/hole (按 selector 激活)。
"""
from __future__ import annotations

from seekflow_engineering_tools.generative_cad.validation_kernel.models import (
    RuleLayer,
    RuleManifest,
    RuleSelector,
)
from seekflow_engineering_tools.generative_cad.validation_kernel.registry import RuleRegistry
from seekflow_engineering_tools.generative_cad.validation_kernel.stages import ValidationStage


def register_legacy_core_rules(reg: RuleRegistry) -> None:
    """按现有 pipeline 顺序登记 Core validator (顺序即注册序)."""
    from seekflow_engineering_tools.generative_cad.validation.composition import (
        validate_composition_requirements,
    )
    from seekflow_engineering_tools.generative_cad.validation.dialect_semantics import (
        validate_dialect_semantics,
    )
    from seekflow_engineering_tools.generative_cad.validation.geometry_preflight import (
        validate_geometry_preflight,
    )
    from seekflow_engineering_tools.generative_cad.validation.graph import validate_graph
    from seekflow_engineering_tools.generative_cad.validation.ownership import validate_ownership
    from seekflow_engineering_tools.generative_cad.validation.params import validate_params
    from seekflow_engineering_tools.generative_cad.validation.phase import validate_phase
    from seekflow_engineering_tools.generative_cad.validation.registry import validate_registry
    from seekflow_engineering_tools.generative_cad.validation.root_terminal import (
        validate_root_terminal,
    )
    from seekflow_engineering_tools.generative_cad.validation.safety import validate_safety
    from seekflow_engineering_tools.generative_cad.validation.structure import validate_structure
    from seekflow_engineering_tools.generative_cad.validation.typecheck import validate_typecheck

    raw_stage_validators = [
        (ValidationStage.STRUCTURE, validate_structure),
        (ValidationStage.ROOT_TERMINAL, validate_root_terminal),
        (ValidationStage.REGISTRY, validate_registry),
        (ValidationStage.PARAMS, validate_params),
        (ValidationStage.OWNERSHIP, validate_ownership),
        (ValidationStage.GRAPH, validate_graph),
        (ValidationStage.TYPECHECK, validate_typecheck),
        (ValidationStage.PHASE, validate_phase),
        (ValidationStage.COMPOSITION, validate_composition_requirements),
        # hole_semantics: 已迁出 → extensions/features/hole (Phase 4)
        (ValidationStage.SAFETY, validate_safety),
    ]
    canonical_stage_validators = [
        (ValidationStage.DIALECT_SEMANTICS, validate_dialect_semantics),
        (ValidationStage.GEOMETRY_PREFLIGHT, validate_geometry_preflight),
    ]

    for stage, fn in raw_stage_validators + canonical_stage_validators:
        reg.register_rule(
            RuleManifest(
                rule_id=f"core.legacy.{stage.value}",
                version="1.0.0",
                provider_id="core.legacy",
                layer=RuleLayer.CORE,
                stage=stage,
                selector=RuleSelector(always=True),
            ),
            fn,
        )
