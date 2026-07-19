"""Validation Kernel — 统一 Stage 定义 (单一事实来源).

对应 docs/text2cad_validation_autofix_refactor_guide_v1.md §4。
Phase 1 (行为冻结): enum 值 == 现有 pipeline 的真实 stage 字符串, 报告输出不变。
文档 §4 的新命名 (INGEST/RAW_STRUCTURE/...) 属 Phase 2 重命名, 届时在此统一切换。

Stage 顺序只在本文件定义一次; repair governor 的 STAGE_RANK 迁移(Phase 2)后
也从这里取序。
"""
from __future__ import annotations
from enum import Enum


class ValidationStage(str, Enum):
    # ── Raw 层 (输入为 RawGcadDocument) ──
    STRUCTURE = "structure"
    ROOT_TERMINAL = "root_terminal"
    REGISTRY = "registry"
    PARAMS = "params"
    OWNERSHIP = "ownership"
    GRAPH = "graph"
    TYPECHECK = "typecheck"
    PHASE = "phase"
    COMPOSITION = "composition"
    HOLE_SEMANTICS = "hole_semantics"   # 已知应迁往 Hole Feature Extension (Phase 4)
    SAFETY = "safety"
    # ── Lowering ──
    CANONICALIZE = "canonicalize"
    # ── Canonical 层 (输入为 CanonicalGcadDocument) ──
    DIALECT_SEMANTICS = "dialect_semantics"
    GEOMETRY_PREFLIGHT = "geometry_preflight"
    # ── Topology persistent naming (Phase 2+) ──
    TOPOLOGY_CONTRACT = "topology_contract"
    TOPOLOGY_REFERENCE = "topology_reference"
    TOPOLOGY_RUNTIME_INTEGRITY = "topology_runtime_integrity"
    TOPOLOGY_ARTIFACT_PROOF = "topology_artifact_proof"
    # ── Runtime/产物层 (repair governor 进度排序用; 不在本 executor 执行) ──
    RUNTIME_POSTCONDITIONS = "runtime_postconditions"
    INSPECTION = "inspection"


# 权威执行顺序 (fail-fast 顺序), 单一来源
RAW_STAGE_ORDER: tuple[ValidationStage, ...] = (
    ValidationStage.STRUCTURE,
    ValidationStage.ROOT_TERMINAL,
    ValidationStage.REGISTRY,
    ValidationStage.PARAMS,
    ValidationStage.OWNERSHIP,
    ValidationStage.GRAPH,
    ValidationStage.TYPECHECK,
    ValidationStage.PHASE,
    ValidationStage.COMPOSITION,
    ValidationStage.HOLE_SEMANTICS,
    ValidationStage.SAFETY,
)

CANONICAL_STAGE_ORDER: tuple[ValidationStage, ...] = (
    ValidationStage.DIALECT_SEMANTICS,
    ValidationStage.GEOMETRY_PREFLIGHT,
)

FULL_STAGE_ORDER: tuple[ValidationStage, ...] = (
    *RAW_STAGE_ORDER,
    ValidationStage.CANONICALIZE,
    *CANONICAL_STAGE_ORDER,
)

# 进度排序用的完整顺序 (含 runtime/产物层)
RANK_ORDER: tuple[ValidationStage, ...] = (
    *FULL_STAGE_ORDER,
    ValidationStage.TOPOLOGY_CONTRACT,
    ValidationStage.TOPOLOGY_REFERENCE,
    ValidationStage.TOPOLOGY_RUNTIME_INTEGRITY,
    ValidationStage.TOPOLOGY_ARTIFACT_PROOF,
    ValidationStage.RUNTIME_POSTCONDITIONS,
    ValidationStage.INSPECTION,
)

# ── Phase 2 barrier 分组 (§4): 组内聚合全部独立 Issue, 组间 barrier ──
# structure 单独成组: 结构/解析失败时后续规则缺乏可靠输入。
RAW_BARRIER_GROUPS: tuple[tuple[ValidationStage, ...], ...] = (
    (ValidationStage.STRUCTURE,),
    (
        ValidationStage.ROOT_TERMINAL,
        ValidationStage.REGISTRY,
        ValidationStage.PARAMS,
        ValidationStage.OWNERSHIP,
        ValidationStage.GRAPH,
        ValidationStage.TYPECHECK,
        ValidationStage.PHASE,
        ValidationStage.COMPOSITION,
        ValidationStage.HOLE_SEMANTICS,
        ValidationStage.SAFETY,
    ),
)

CANONICAL_BARRIER_GROUPS: tuple[tuple[ValidationStage, ...], ...] = (
    CANONICAL_STAGE_ORDER,
    # Topology advisory: runs after canonical validation, never fails build (Phase 7)
    (ValidationStage.TOPOLOGY_CONTRACT,),
)


def stage_rank(stage: str | ValidationStage) -> int:
    """stage → 顺位 (0 起)。未知 stage 返回 -1 (调用方 fail-closed)。"""
    try:
        s = ValidationStage(stage)
    except ValueError:
        return -1
    return RANK_ORDER.index(s)


def governor_stage_rank(stage: str | ValidationStage) -> int:
    """repair governor 兼容 rank: 正整数=有效顺位, 0=未知 (governor 跳过回归检查).

    取代 repair/governor.py 曾自维护的 STAGE_RANK 字典 (已双向漂移),
    顺序单一来源自 RANK_ORDER。"""
    r = stage_rank(stage)
    return 0 if r < 0 else (r + 1) * 10
