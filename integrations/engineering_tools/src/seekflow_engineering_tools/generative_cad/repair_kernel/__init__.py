"""Repair Kernel — Issue-driven 修复引擎 (指导书 §8, Phase 3).

validate → propose → 原子应用 → revalidate → QualityVector 严格验收。
Phase 3: LegacyAutoFixProvider 单一提供者; Phase 4+ 按扩展抽取细粒度
RepairProvider (订阅具体 issue code)。
"""
from seekflow_engineering_tools.generative_cad.repair_kernel.models import (
    QualityVector,
    RepairAttemptRecord,
    RepairOutcome,
    RepairProviderManifest,
    RepairRisk,
    is_strict_improvement,
)
from seekflow_engineering_tools.generative_cad.repair_kernel.providers import (
    DialectAliasRepairProvider,
    LegacyAutoFixProvider,
    OpVersionRepairProvider,
    SanitizeRepairProvider,
    SchemaDefaultRepairProvider,
    default_providers,
    provider_matches,
)
from seekflow_engineering_tools.generative_cad.repair_kernel.engine import (
    RepairResult,
    repair_documents,
)
from seekflow_engineering_tools.generative_cad.repair_kernel.config import (
    RepairLoopConfig,
)
from seekflow_engineering_tools.generative_cad.repair_kernel.classifier import (
    RuntimeFailureClass,
    classify_runtime_failure,
)
from seekflow_engineering_tools.generative_cad.repair_kernel.orchestrator import (
    RepairLoopOutcome,
    RepairLoopResult,
    check_patch_common,
    check_runtime_patch,
    run_generation_loop,
)

__all__ = [
    "QualityVector", "RepairAttemptRecord", "RepairOutcome",
    "RepairProviderManifest", "RepairRisk", "is_strict_improvement",
    "LegacyAutoFixProvider", "OpVersionRepairProvider",
    "SanitizeRepairProvider", "SchemaDefaultRepairProvider",
    "DialectAliasRepairProvider",
    "default_providers", "provider_matches",
    "RepairResult", "repair_documents",
    "RepairLoopConfig", "RuntimeFailureClass", "classify_runtime_failure",
    "RepairLoopOutcome", "RepairLoopResult", "check_patch_common",
    "check_runtime_patch", "run_generation_loop",
]
