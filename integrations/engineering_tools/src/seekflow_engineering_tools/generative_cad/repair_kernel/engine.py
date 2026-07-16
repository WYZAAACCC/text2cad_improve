"""Repair Engine — validate → propose → 原子应用 → revalidate → 质量验收 (§8.6).

取代 Web 层 "validate 失败 → try: auto_fix; except: pass" 的编排:
- 修复由具体 Issue 触发, Provider 按订阅的 issue code 匹配 (细粒度优先, legacy 兜底);
- 风险门控: RepairPolicy.auto_apply_risks / allow_legacy_chain (§8.3);
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
    default_providers,
    provider_matches,
)


class RepairResult:
    """repair loop 的完整返回: 最终文档/验证结果 + outcome 审计."""

    def __init__(self, document: dict, run, outcome: RepairOutcome) -> None:
        self.document = document          # 接受修复时为 fixed dict, 否则原文档
        self.run = run                    # 最终 ValidationRun (与 document 对应)
        self.outcome = outcome


def _policy_allows(provider, policy) -> bool:
    risk = provider.manifest.risk
    if risk == "mixed_legacy":
        return policy.repair.allow_legacy_chain
    return risk in policy.repair.auto_apply_risks


def repair_documents(
    raw_doc: dict,
    initial_run,
    *,
    dialect_registry=None,
    providers: list | None = None,
    policy=None,
) -> RepairResult:
    """Issue-driven repair loop.

    Provider 顺序尝试 (细粒度优先, legacy 兜底), 每轮至多接受一个提案;
    接受后重入下一轮 (剩余错误可能由其它 Provider 处理), 直至 ok /
    无 Provider 可用 / 达到 policy.repair.max_attempts 轮。
    """
    from seekflow_engineering_tools.generative_cad.validation_kernel.executor import (
        run_validation,
    )
    from seekflow_engineering_tools.generative_cad.validation_kernel.policy import (
        default_validation_policy,
    )

    policy = policy or default_validation_policy()
    providers = providers if providers is not None else default_providers(dialect_registry)

    outcome = RepairOutcome()
    document = raw_doc
    run = initial_run
    result = RepairResult(document, run, outcome)
    result.provider = None  # 最近一次实际提案的 provider (main.py 落盘用)

    for _round in range(max(1, policy.repair.max_attempts)):
        if run.report.ok:
            break

        accepted_this_round = False

        for provider in providers:
            if run.report.ok:
                break
            # 级联: 每个 provider 基于**当前**文档/错误集提案 —
            # 同轮内接受后继续尝试后续 provider (细粒度化不降低单轮修复能力)
            q_before = QualityVector.from_report(run.report)
            issue_codes = {getattr(i, "code", "") for i in run.report.issues
                           if getattr(i, "severity", "") == "error"}
            if not provider_matches(provider, issue_codes):
                continue
            if not _policy_allows(provider, policy):
                outcome.records.append(RepairAttemptRecord(
                    provider_id=provider.manifest.provider_id,
                    provider_version=provider.manifest.version,
                    risk=provider.manifest.risk,
                    triggered_by_issue_codes=sorted(issue_codes),
                    reject_reason="risk not allowed by policy",
                    quality_before=q_before,
                ))
                continue

            record = RepairAttemptRecord(
                provider_id=provider.manifest.provider_id,
                provider_version=provider.manifest.version,
                risk=provider.manifest.risk,
                triggered_by_issue_codes=sorted(issue_codes),
                quality_before=q_before,
            )
            outcome.attempts += 1
            result.provider = provider

            try:
                candidate, rule_ids = provider.propose(document, run.report.issues)
                record.applied_rule_ids = rule_ids
            except Exception as exc:
                # 修复框架异常: 记录, 试下一个 Provider — 不静默 (§1.8)
                record.error = f"{exc}\n{traceback.format_exc()[-1500:]}"
                outcome.records.append(record)
                continue

            if not rule_ids:
                record.reject_reason = "no fixes applicable"
                outcome.records.append(record)
                continue

            # 候选验证 (完整管线 = 全量 barrier 回归)
            try:
                candidate_run = run_validation(candidate)
            except Exception as exc:
                record.error = f"revalidation crashed: {exc}\n{traceback.format_exc()[-1500:]}"
                outcome.records.append(record)
                continue

            q_after = QualityVector.from_report(
                candidate_run.report, baseline_error_codes=issue_codes)
            record.quality_after = q_after

            if is_strict_improvement(q_before, q_after):
                record.accepted = True
                outcome.accepted = True
                document = candidate
                run = candidate_run
                accepted_this_round = True
                outcome.records.append(record)
                continue   # 级联: 在更新后的文档上继续尝试后续 provider
            # 质量未严格改善 → 丢弃候选 (原子回滚), 试下一个 Provider
            record.reject_reason = (
                f"quality not strictly improved: before={q_before.key()} after={q_after.key()}")
            outcome.records.append(record)

        if run.report.ok or not accepted_this_round:
            break   # 完成 / 本轮无任何改善 → 停止 (有改善则下一轮重头处理新暴露错误)

    outcome.final_ok = run.report.ok
    result.document = document
    result.run = run
    return result
