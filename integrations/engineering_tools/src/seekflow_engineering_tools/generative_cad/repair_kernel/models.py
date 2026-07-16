"""Repair Kernel — Issue-driven Repair 数据模型 (指导书 §8).

统一取代"两套 Repair 安全合同"(§1.6): RepairProvider 订阅 Issue、
产出 Proposal、经质量向量验收 —— 不再有"验证失败后盲跑全部修复"的路径。
"""
from __future__ import annotations
from typing import Literal

from pydantic import BaseModel, Field

RepairRisk = Literal[
    "normalization",
    "contract_derived",
    "geometry_recovery",
    "domain_semantic",
    "intent_changing",
    "destructive",
    "mixed_legacy",   # LegacyAutoFixProvider 专用: 旧 auto_fix 链风险混杂, 如实标注
]


class RepairProviderManifest(BaseModel):
    provider_id: str
    version: str = "1.0.0"
    handles_issue_codes: set[str] = Field(default_factory=set)  # {"*"} = 全部 (仅 legacy)
    risk: RepairRisk = "contract_derived"
    deterministic: bool = True


#: ok 报告的 blocked_stage_rank 哨兵 — 恒大于任何真实 stage rank
OK_STAGE_SENTINEL = 10**6


class QualityVector(BaseModel):
    """验证质量向量 (§8.5) — 字典序比较.

    new_issue_count: 相对基线**新引入**的 error issue code 数 — 防止
    "修好 2 个旧错、引入 1 个新错" 因计数下降被接受 (审查 M4)。
    blocked_stage_rank: 首个失败 stage 的 governor rank
    (report.stage, barrier 分组下即最早失败点; 单一 rank 来源
    validation_kernel.stages.governor_stage_rank)。ok 时取大哨兵值。
    """
    error_count: int = 0
    warning_count: int = 0
    new_issue_count: int = 0
    blocked_stage_rank: int = 0
    ok: bool = False

    @classmethod
    def from_report(cls, report, baseline_error_codes: set[str] | None = None) -> "QualityVector":
        from seekflow_engineering_tools.generative_cad.validation_kernel.stages import (
            governor_stage_rank,
        )

        errors = [i for i in report.issues if getattr(i, "severity", "") == "error"]
        warnings = sum(1 for i in report.issues if getattr(i, "severity", "") == "warning")
        new_count = 0
        if baseline_error_codes is not None:
            new_count = sum(1 for i in errors
                            if getattr(i, "code", "") not in baseline_error_codes)
        if report.ok:
            blocked = OK_STAGE_SENTINEL
        else:
            blocked = governor_stage_rank(getattr(report, "stage", "") or "")
        return cls(error_count=len(errors), warning_count=warnings,
                   new_issue_count=new_count,
                   blocked_stage_rank=blocked, ok=report.ok)

    def key(self) -> tuple:
        # 字典序: ok > 失败点深度 > error 净数 > 新引入错误数 > warning。
        # -blocked_stage_rank 置于 error_count 之前 (指导书 §11.2 优先级 2):
        # "推进型修复" (parse 层修好 → 暴露更深 stage 的错误, 即使数量增加)
        # 视为严格改善 — 深层暴露的错误属预期, 由级联/下一轮继续处理,
        # 最终仍受 main 链 "有 error 即失败" 把关。
        # 同 stage 内沿用原语义: error_count 优先于 new_issue_count =
        # "净进步"策略 — 修好 2 个旧错、引入 1 个新错 (3→2) 会被接受,
        # 弱于指导书 §8.5 的 "不新增任何 Core Error" 严格条件;
        # 换来的是可接受渐进修复 (取舍显式记录)。
        # 未知 stage → rank 0 = 最少进步, fail-closed。
        return (0 if self.ok else 1,
                -self.blocked_stage_rank, self.error_count,
                self.new_issue_count, self.warning_count)


def is_strict_improvement(before: QualityVector, after: QualityVector) -> bool:
    """接受修复的最低条件 (§8.5): 质量向量严格改善."""
    return after.key() < before.key()


class RepairAttemptRecord(BaseModel):
    """一次修复尝试的执行记录 — 异常/拒绝不得静默 (§8.6)."""
    provider_id: str
    provider_version: str = "1.0.0"
    risk: RepairRisk = "mixed_legacy"
    triggered_by_issue_codes: list[str] = Field(default_factory=list)
    applied_rule_ids: list[str] = Field(default_factory=list)
    accepted: bool = False
    reject_reason: str | None = None
    error: str | None = None
    quality_before: QualityVector | None = None
    quality_after: QualityVector | None = None


class RepairOutcome(BaseModel):
    """repair loop 总结果, 落盘为 repair_execution.json."""
    attempts: int = 0
    accepted: bool = False
    final_ok: bool = False
    records: list[RepairAttemptRecord] = Field(default_factory=list)
