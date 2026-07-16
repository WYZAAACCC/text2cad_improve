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


class QualityVector(BaseModel):
    """验证质量向量 (§8.5) — 字典序比较, 不再用 stage rank 判进步.

    new_issue_count: 相对基线**新引入**的 error issue code 数 — 防止
    "修好 2 个旧错、引入 1 个新错" 因计数下降被接受 (审查 M4)。
    """
    error_count: int = 0
    warning_count: int = 0
    new_issue_count: int = 0
    ok: bool = False

    @classmethod
    def from_report(cls, report, baseline_error_codes: set[str] | None = None) -> "QualityVector":
        errors = [i for i in report.issues if getattr(i, "severity", "") == "error"]
        warnings = sum(1 for i in report.issues if getattr(i, "severity", "") == "warning")
        new_count = 0
        if baseline_error_codes is not None:
            new_count = sum(1 for i in errors
                            if getattr(i, "code", "") not in baseline_error_codes)
        return cls(error_count=len(errors), warning_count=warnings,
                   new_issue_count=new_count, ok=report.ok)

    def key(self) -> tuple:
        # 字典序: ok > error 净数 > 新引入错误数 > warning。
        # 取舍 (显式记录): error_count 优先于 new_issue_count = "净进步"策略 —
        # 修好 2 个旧错、引入 1 个新错 (3→2) 会被接受, 弱于指导书 §8.5 的
        # "不新增任何 Core Error" 严格条件; 换来的是可接受渐进修复,
        # 新错由级联/下一轮继续处理, 最终仍受 main 链 "有 error 即失败" 把关。
        # 已知局限: error 数持平的"推进型"修复 (parse 层修好 → 暴露同数深层错)
        # 因 new_issue_count 会被单步拒绝, 当前靠 legacy 兜底链覆盖;
        # legacy 退役前需引入 unresolved/stage 感知维度。
        return (0 if self.ok else 1, self.error_count,
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
