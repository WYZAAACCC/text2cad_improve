"""Full validation pipeline — RawGcadDocument → CanonicalGcadDocument.

v0.7: 实现迁移至 validation_kernel (Registry + Executor), 本模块保留为
公共 API 兼容 wrapper。行为与 v0.6 完全一致, 由
tests/generative_cad/golden_validation 行为基线锁定。

RAW_STAGES / CANONICAL_STAGES 的权威定义现位于:
  validation_kernel/stages.py   (stage 枚举与顺序, 单一来源)
  validation_kernel/legacy_adapter.py  (validator 登记)
"""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalGcadDocument
from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
from seekflow_engineering_tools.generative_cad.validation.reports import ValidationReport


def validate_and_canonicalize_with_bundle(
    raw: dict | RawGcadDocument,
) -> tuple[CanonicalGcadDocument | None, ValidationReport, "ValidationBundle"]:
    """Full pipeline returning structured ValidationBundle.

    Deprecated compatibility path — 委托 validation_kernel.run_validation,
    需要 RuleExecutionRecord 的新代码请直接使用 run_validation()。
    """
    from seekflow_engineering_tools.generative_cad.validation_kernel.executor import (
        run_validation,
    )
    run = run_validation(raw)
    return run.canonical, run.report, run.bundle


def validate_and_canonicalize(
    raw: dict | RawGcadDocument,
) -> tuple[CanonicalGcadDocument | None, ValidationReport]:
    """Full fail-closed validation pipeline. Backward-compatible wrapper."""
    canonical, report, _bundle = validate_and_canonicalize_with_bundle(raw)
    return canonical, report
