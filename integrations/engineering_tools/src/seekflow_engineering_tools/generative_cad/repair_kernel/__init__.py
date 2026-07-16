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
    LegacyAutoFixProvider,
)
from seekflow_engineering_tools.generative_cad.repair_kernel.engine import (
    RepairResult,
    repair_documents,
)

__all__ = [
    "QualityVector", "RepairAttemptRecord", "RepairOutcome",
    "RepairProviderManifest", "RepairRisk", "is_strict_improvement",
    "LegacyAutoFixProvider", "RepairResult", "repair_documents",
]
