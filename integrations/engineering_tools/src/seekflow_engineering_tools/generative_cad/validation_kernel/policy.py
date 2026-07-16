"""统一 Validation / Repair Policy (指导书 §16).

所有阈值集中于此, 不再散落为模块常量。默认值 == 迁移前的模块常量
(行为冻结); 部署可传入自定义实例覆盖。
Extension 自有阈值须命名空间化, 放各自扩展包内, 不进本文件。
"""
from __future__ import annotations
from functools import lru_cache

from pydantic import BaseModel, Field


class GeometryPolicy(BaseModel):
    """通用几何预检阈值 — 迁移自 validation/geometry_preflight.DEFAULT_GEOMETRY_POLICY."""
    max_nodes: int = 64
    max_boolean_ops: int = 256
    max_profile_points: int = 128
    min_edge_length_mm: float = 0.25
    min_wall_thickness_mm: float = 1.0
    min_boolean_clearance_mm: float = 0.2
    min_hole_to_boundary_margin_mm: float = 1.0
    max_pattern_instances: int = 360
    max_fillet_ratio_to_local_thickness: float = 0.25


class RepairPolicy(BaseModel):
    """修复风险策略 (指导书 §8.3). 默认值 == 当前生产行为."""
    max_attempts: int = 1
    auto_apply_risks: set[str] = Field(default_factory=lambda: {
        "normalization", "contract_derived", "geometry_recovery",
    })
    # legacy auto_fix 链风险混杂 (mixed_legacy); 细粒度 Provider 全量就位前
    # 由此开关显式放行 (Phase 5 终局默认改 False)
    allow_legacy_chain: bool = True


class ValidationPolicy(BaseModel):
    geometry: GeometryPolicy = Field(default_factory=GeometryPolicy)
    repair: RepairPolicy = Field(default_factory=RepairPolicy)


@lru_cache(maxsize=1)
def default_validation_policy() -> ValidationPolicy:
    return ValidationPolicy()
