"""Repair Engine — validate → propose → 原子应用 → revalidate → 质量验收 (§8.6).

取代 Web 层 "validate 失败 → try: auto_fix; except: pass" 的编排:
- 修复由具体 Issue 触发;
- 候选文档在副本上产生, 质量向量严格改善才接受, 否则丢弃 (回滚);
- 全部异常进入 RepairAttemptRecord, 禁止静默;
- 进度判断用 QualityVector, 不用 stage rank。
"""
from __future__ import annotations
import traceback

from seekflow_engineering_tools.generative_cad.repair_kernel.models import (
    QualityVector,
    RepairAttemptRecord,
    RepairOutcome,
    is_strict_improvement,
)
from seekflow_engineering_tools.generative_cad.repair_kernel.providers import (
    LegacyAutoFixProvider,
)


class RepairResult:
    """repair loop 的完整返回: 最终文档/验证结果 + outcome 审计."""

    def __init__(self, document: dict, run, outcome: RepairOutcome) -> None:
        self.document = document          # 接受修复时为 fixed dict, 否则原文档
        self.run = run                    # 最终 ValidationRun (与 document 对应)
        self.outcome = outcome


def repair_documents(
    raw_doc: dict,
    initial_run,
    *,
    dialect_registry=None,
    max_attempts: int = 1,
) -> RepairResult:
    """Issue-driven repair loop (Phase 3: 单一 LegacyAutoFixProvider).

    initial_run: 已失败的 ValidationRun (由调用方先 validate 得到)。
    legacy 链确定性 → 同输入重跑无意义, max_attempts 默认 1;
    Phase 4+ 引入细粒度 Provider 后循环才有多轮价值。
    """
    from seekflow_engineering_tools.generative_cad.validation_kernel.executor import (
        run_validation,
    )

    outcome = RepairOutcome()
    document = raw_doc
    run = initial_run

    provider = LegacyAutoFixProvider(dialect_registry)

    for _ in range(max_attempts):
        if run.report.ok:
            break

        q_before = QualityVector.from_report(run.report)
        issue_codes = sorted({getattr(i, "code", "") for i in run.report.issues
                              if getattr(i, "severity", "") == "error"})
        record = RepairAttemptRecord(
            provider_id=provider.manifest.provider_id,
            provider_version=provider.manifest.version,
            risk=provider.manifest.risk,
            triggered_by_issue_codes=issue_codes,
            quality_before=q_before,
        )
        outcome.attempts += 1

        try:
            candidate, rule_ids = provider.propose(document, run.report.issues)
            record.applied_rule_ids = rule_ids
        except Exception as exc:
            # 修复框架异常: 记录并停止 — 区分"无修复方案"与"框架崩溃" (§1.8)
            record.error = f"{exc}\n{traceback.format_exc()[-1500:]}"
            outcome.records.append(record)
            break

        if not rule_ids:
            record.reject_reason = "no fixes applicable"
            outcome.records.append(record)
            break

        # 候选验证 (完整管线 = 全量 barrier 回归)
        try:
            candidate_run = run_validation(candidate)
        except Exception as exc:
            record.error = f"revalidation crashed: {exc}\n{traceback.format_exc()[-1500:]}"
            outcome.records.append(record)
            break

        q_after = QualityVector.from_report(candidate_run.report)
        record.quality_after = q_after

        if is_strict_improvement(q_before, q_after):
            record.accepted = True
            outcome.accepted = True
            document = candidate
            run = candidate_run
        else:
            # 质量未严格改善 → 丢弃候选 (原子回滚: document/run 保持不变)
            record.reject_reason = (
                f"quality not strictly improved: before={q_before.key()} after={q_after.key()}")
        outcome.records.append(record)

        if record.accepted and run.report.ok:
            break
        if not record.accepted:
            break  # legacy 链确定性, 重试同样结果

    outcome.final_ok = run.report.ok
    result = RepairResult(document, run, outcome)
    result.provider = provider  # 暴露 last_report 供调用方落盘 autofix_report.json
    return result
