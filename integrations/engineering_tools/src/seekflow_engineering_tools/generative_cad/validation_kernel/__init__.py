"""Validation Kernel — 微内核 + 自动加载扩展的规则系统.

对应 docs/text2cad_validation_autofix_refactor_guide_v1.md。
Phase 1 (当前): 统一 Stage/Rule/Extension 模型 + RuleRegistry +
LegacyRuleAdapter + Executor, 行为与旧 validation/pipeline.py 完全一致
(tests/generative_cad/golden_validation 基线锁定)。

后续阶段 (见指导书 §17): Phase 2 同 stage 聚合 / Phase 3 repair_kernel /
Phase 4 抽取 hole/axisymmetric/turbine_disk 扩展 / Phase 5 删除双轨。
"""
from seekflow_engineering_tools.generative_cad.validation_kernel.stages import (
    ValidationStage,
    RAW_STAGE_ORDER,
    CANONICAL_STAGE_ORDER,
    FULL_STAGE_ORDER,
    stage_rank,
)
from seekflow_engineering_tools.generative_cad.validation_kernel.models import (
    RuleLayer,
    RuleSelector,
    RuleManifest,
    RuleExecutionRecord,
    ActivationSnapshot,
    ExtensionManifest,
)
from seekflow_engineering_tools.generative_cad.validation_kernel.registry import (
    RuleRegistry,
    RuleRegistryError,
    default_rule_registry,
)
from seekflow_engineering_tools.generative_cad.validation_kernel.executor import (
    ValidationRun,
    run_validation,
)

__all__ = [
    "ValidationStage", "RAW_STAGE_ORDER", "CANONICAL_STAGE_ORDER",
    "FULL_STAGE_ORDER", "stage_rank",
    "RuleLayer", "RuleSelector", "RuleManifest", "RuleExecutionRecord",
    "ActivationSnapshot", "ExtensionManifest",
    "RuleRegistry", "RuleRegistryError", "default_rule_registry",
    "ValidationRun", "run_validation",
]
