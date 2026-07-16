"""Validation Executor — 从 Registry 取规则执行完整验证管线.

Phase 2 (§4 barrier 语义): 同一 barrier 组内运行全部规则并聚合独立 Issue
(不再在组内首个失败 stage 停止), 组间保持 barrier —— 前组失败时后组规则
产生 RuleExecutionRecord(status="skipped"), 不静默消失。

分组定义 (单一来源): validation_kernel/stages.py 的 *_BARRIER_GROUPS。
输出契约不变: (canonical, ValidationReport, ValidationBundle);
失败 report.stage = 首个失败 stage。
"""
from __future__ import annotations

from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
from seekflow_engineering_tools.generative_cad.validation.canonicalize import canonicalize
from seekflow_engineering_tools.generative_cad.validation.reports import ValidationReport
from seekflow_engineering_tools.generative_cad.validation_kernel.models import (
    ActivationSnapshot,
    RuleExecutionRecord,
)
from seekflow_engineering_tools.generative_cad.validation_kernel.registry import (
    RegisteredRule,
    RuleRegistry,
    default_rule_registry,
)
from seekflow_engineering_tools.generative_cad.validation_kernel.stages import (
    CANONICAL_BARRIER_GROUPS,
    RAW_BARRIER_GROUPS,
)
import time


class ValidationRun:
    """一次验证的完整结果: 原 API 三元组 + 规则执行记录 + 激活快照."""

    def __init__(self, canonical, report, bundle,
                 execution_records: list[RuleExecutionRecord],
                 activation: ActivationSnapshot | None = None) -> None:
        self.canonical = canonical
        self.report = report
        self.bundle = bundle
        self.execution_records = execution_records
        self.activation = activation or ActivationSnapshot()


def _run_barrier_groups(
    subject,
    groups: list[list[tuple[str, RegisteredRule]]],
    all_issues: list,
    stages_run: list[str],
    records: list[RuleExecutionRecord],
) -> tuple[bool, str | None, dict[str, ValidationReport]]:
    """Barrier 语义: 组内聚合全部规则的 Issue; 任一组有失败则后续组 skipped.

    返回 (ok, first_failed_stage, reports)。异常包装语义与 v0.6 一致
    ({stage}_validator_exception), 但不再中断组内其余规则。
    """
    reports: dict[str, ValidationReport] = {}
    first_failed: str | None = None

    for gi, group in enumerate(groups):
        if first_failed is not None:
            # 前组已失败 → 本组全部 skipped (结构化记录, 不静默)
            for stage_name, rule in group:
                records.append(RuleExecutionRecord(
                    rule_id=rule.manifest.rule_id,
                    rule_version=rule.manifest.version,
                    provider_id=rule.manifest.provider_id,
                    stage=stage_name,
                    status="skipped",
                    skip_reason=f"barrier: earlier stage {first_failed!r} failed",
                ))
            continue

        for stage_name, rule in group:
            t0 = time.perf_counter()
            try:
                report = rule.evaluate(subject)
                status = "passed" if report.ok else "failed"
            except Exception as exc:
                report = ValidationReport.fail(
                    stage=stage_name,
                    code=f"{stage_name}_validator_exception",
                    message=str(exc),
                    stages_run=list(stages_run) + [stage_name],
                )
                status = "provider_error"

            if not report.stages_run:
                report.stages_run = list(stages_run) + [stage_name]

            reports[stage_name] = report
            all_issues.extend(report.issues)
            stages_run.append(stage_name)
            records.append(RuleExecutionRecord(
                rule_id=rule.manifest.rule_id,
                rule_version=rule.manifest.version,
                provider_id=rule.manifest.provider_id,
                stage=stage_name,
                status=status,
                duration_ms=(time.perf_counter() - t0) * 1000.0,
                issue_count=len(report.issues),
            ))

            if not report.ok and first_failed is None:
                first_failed = stage_name
                # 组内继续 — §4: 同一层级其他独立问题一次收集

    return first_failed is None, first_failed, reports


def run_validation(
    raw: dict | RawGcadDocument,
    *,
    registry: RuleRegistry | None = None,
    activation: ActivationSnapshot | None = None,
) -> ValidationRun:
    """完整验证管线 — 输出与旧 validate_and_canonicalize_with_bundle 三元组一致."""
    from seekflow_engineering_tools.generative_cad.validation.bundle import ValidationBundle

    registry = registry or default_rule_registry()
    records: list[RuleExecutionRecord] = []

    def _barrier_groups(group_defs) -> list[list[tuple[str, RegisteredRule]]]:
        groups: list[list[tuple[str, RegisteredRule]]] = []
        for stage_tuple in group_defs:
            group: list[tuple[str, RegisteredRule]] = []
            for stage in stage_tuple:
                for rule in registry.select(stage, activation):
                    group.append((stage.value, rule))
            groups.append(group)
        return groups

    stages_run: list[str] = []
    all_issues: list = []

    # ── Parse raw (原样移动自 pipeline.py) ──
    if isinstance(raw, dict):
        from seekflow_engineering_tools.generative_cad.ir.parse import parse_raw_gcad_document
        from seekflow_engineering_tools.generative_cad.validation.reports import ValidationIssue
        parse_result = parse_raw_gcad_document(raw)
        if not parse_result.ok:
            stages_run.append("structure")
            for issue in parse_result.issues:
                all_issues.append(ValidationIssue(
                    stage="structure",
                    code=issue.code,
                    message=issue.message,
                    severity=issue.severity,
                    path=issue.path,
                ))
            report = ValidationReport(
                ok=False, stage="structure", issues=list(all_issues),
                stages_run=list(stages_run),
            )
            bundle = ValidationBundle(ok=False, raw_stage_reports={}, canonicalize_report=None, canonical_stage_reports={})
            return ValidationRun(None, report, bundle, records)
        raw = parse_result.document

    # ── Extension activation (§6.2: 从文档明确元数据解析, 禁止名称猜测) ──
    if activation is None:
        from seekflow_engineering_tools.generative_cad.validation_kernel.activation import (
            resolve_activation_from_document,
        )
        activation = resolve_activation_from_document(raw)

    # ── Raw barrier groups (§4: 组内聚合, 组间 barrier) ──
    ok, failed_stage, raw_stage_reports = _run_barrier_groups(
        raw, _barrier_groups(RAW_BARRIER_GROUPS), all_issues, stages_run, records,
    )

    if not ok:
        report = ValidationReport(ok=False, stage=failed_stage, issues=all_issues, stages_run=list(stages_run))
        bundle = ValidationBundle(ok=False, raw_stage_reports=raw_stage_reports, canonicalize_report=None, canonical_stage_reports={})
        return ValidationRun(None, report, bundle, records, activation)

    # ── Lowering (canonicalize 是产出文档的固定步骤, 不作为 Rule 注册) ──
    canonical, c_report = canonicalize(raw)
    all_issues.extend(c_report.issues)
    stages_run.append("canonicalize")
    records.append(RuleExecutionRecord(
        rule_id="core.legacy.canonicalize", stage="canonicalize",
        status="passed" if c_report.ok else "failed",
        issue_count=len(c_report.issues),
    ))
    if not c_report.ok:
        report = ValidationReport(ok=False, stage="canonicalize", issues=all_issues, stages_run=list(stages_run))
        bundle = ValidationBundle(ok=False, raw_stage_reports=raw_stage_reports, canonicalize_report=c_report, canonical_stage_reports={})
        return ValidationRun(None, report, bundle, records, activation)

    # ── Canonical barrier groups ──
    ok, failed_stage, canonical_stage_reports = _run_barrier_groups(
        canonical, _barrier_groups(CANONICAL_BARRIER_GROUPS), all_issues, stages_run, records,
    )

    # ── Repair hints (原样移动, 含原 try/except 的 advisory 语义) ──
    repair_hints_text = ""
    error_issues = [i for i in all_issues if getattr(i, 'severity', '') == 'error']
    if error_issues:
        try:
            from seekflow_engineering_tools.generative_cad.validation.repair_hints import (
                build_repair_hints_from_validation,
            )
            temp_report = ValidationReport(
                ok=False, stage="complete",
                issues=list(all_issues), stages_run=list(stages_run),
            )
            repair_hints_text = build_repair_hints_from_validation(temp_report)
        except Exception:
            pass  # Non-critical — hints are advisory only

    if not ok:
        report = ValidationReport(ok=False, stage=failed_stage, issues=all_issues, stages_run=list(stages_run))
        bundle = ValidationBundle(ok=False, raw_stage_reports=raw_stage_reports, canonicalize_report=c_report, canonical_stage_reports=canonical_stage_reports)
        if repair_hints_text:
            bundle.repair_hints = repair_hints_text  # type: ignore[attr-defined]
        return ValidationRun(None, report, bundle, records, activation)

    report = ValidationReport(ok=True, stage="complete", issues=all_issues, stages_run=list(stages_run))
    bundle = ValidationBundle(ok=True, raw_stage_reports=raw_stage_reports, canonicalize_report=c_report, canonical_stage_reports=canonical_stage_reports)
    if repair_hints_text:
        bundle.repair_hints = repair_hints_text  # type: ignore[attr-defined]
    return ValidationRun(canonical, report, bundle, records, activation)
