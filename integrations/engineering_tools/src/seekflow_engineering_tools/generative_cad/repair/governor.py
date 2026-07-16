"""Repair governor v0.4 — track state, enforce stop conditions.

Stage 进度排序自 v0.4 起单一来源于 validation_kernel/stages.py (RANK_ORDER),
本模块曾自维护的 STAGE_RANK 字典已删除 (与 pipeline 双向漂移: 含不存在的
stage、缺 root_terminal/hole_semantics)。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from seekflow_engineering_tools.generative_cad.validation_kernel.stages import (
    governor_stage_rank,
)


class RepairStateV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempts: int = 0
    max_attempts: int = 3
    raw_graph_hashes: list[str] = Field(default_factory=list)
    canonical_graph_hashes: list[str] = Field(default_factory=list)
    error_signature_hashes: list[str] = Field(default_factory=list)
    repair_patch_hashes: list[str] = Field(default_factory=list)
    last_stage_rank: int = 0


def stage_rank_for(stage_name: str) -> int:
    """stage 名 → governor rank (正整数; 未知 stage → 0, 跳过回归检查)."""
    return governor_stage_rank(stage_name)


def can_repair_v2(
    state: RepairStateV2,
    raw_graph_hash: str | None = None,
    error_sig_hash: str | None = None,
    patch_hash: str | None = None,
    current_stage_rank: int = 0,
) -> tuple[bool, str]:
    """Check if repair is allowed.

    Returns (allowed, reason).
    """
    if state.attempts >= state.max_attempts:
        return False, f"Max attempts ({state.max_attempts}) reached"

    if raw_graph_hash is not None:
        if raw_graph_hash in state.raw_graph_hashes:
            return False, "Raw graph hash repeated — LLM not making progress"

    if error_sig_hash is not None:
        count = state.error_signature_hashes.count(error_sig_hash)
        if count >= 2:
            return False, "Same error signature repeated twice — repair not helping"

    if patch_hash is not None:
        if patch_hash in state.repair_patch_hashes:
            return False, "Repair patch hash repeated — looping"

    if current_stage_rank > 0 and state.last_stage_rank > 0:
        # v0.4: only reject regression, not equal stage
        if current_stage_rank < state.last_stage_rank:
            return False, "Validation regressed to an earlier stage"
        # Same stage + same error signature = no progress
        if current_stage_rank == state.last_stage_rank and error_sig_hash is not None and error_sig_hash in state.error_signature_hashes:
            return False, "Same stage and same error signature repeated — repair not helping"

    return True, ""


def update_repair_state_v2(
    state: RepairStateV2,
    raw_graph_hash: str | None = None,
    canonical_graph_hash: str | None = None,
    error_sig_hash: str | None = None,
    patch_hash: str | None = None,
    stage_rank: int = 0,
) -> RepairStateV2:
    """Return a new RepairStateV2 with updated fields."""
    return RepairStateV2(
        attempts=state.attempts + 1,
        max_attempts=state.max_attempts,
        raw_graph_hashes=list(state.raw_graph_hashes) + ([raw_graph_hash] if raw_graph_hash else []),
        canonical_graph_hashes=list(state.canonical_graph_hashes) + ([canonical_graph_hash] if canonical_graph_hash else []),
        error_signature_hashes=list(state.error_signature_hashes) + ([error_sig_hash] if error_sig_hash else []),
        repair_patch_hashes=list(state.repair_patch_hashes) + ([patch_hash] if patch_hash else []),
        last_stage_rank=stage_rank,
    )
