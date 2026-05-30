"""Full validation pipeline — RawGcadDocument → CanonicalGcadDocument.

v0.6: single-pass validators, no double-run.
"""

from __future__ import annotations

from typing import Callable

from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalGcadDocument
from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
from seekflow_engineering_tools.generative_cad.validation.canonicalize import canonicalize
from seekflow_engineering_tools.generative_cad.validation.composition import validate_composition_requirements
from seekflow_engineering_tools.generative_cad.validation.dialect_semantics import validate_dialect_semantics
from seekflow_engineering_tools.generative_cad.validation.geometry_preflight import validate_geometry_preflight
from seekflow_engineering_tools.generative_cad.validation.graph import validate_graph
from seekflow_engineering_tools.generative_cad.validation.ownership import validate_ownership
from seekflow_engineering_tools.generative_cad.validation.params import validate_params
from seekflow_engineering_tools.generative_cad.validation.phase import validate_phase
from seekflow_engineering_tools.generative_cad.validation.registry import validate_registry
from seekflow_engineering_tools.generative_cad.validation.reports import ValidationReport
from seekflow_engineering_tools.generative_cad.validation.safety import validate_safety
from seekflow_engineering_tools.generative_cad.validation.structure import validate_structure
from seekflow_engineering_tools.generative_cad.validation.typecheck import validate_typecheck

RAW_STAGES = [
    ("structure", validate_structure),
    ("registry", validate_registry),
    ("params", validate_params),
    ("ownership", validate_ownership),
    ("graph", validate_graph),
    ("typecheck", validate_typecheck),
    ("phase", validate_phase),
    ("composition", validate_composition_requirements),
    ("safety", validate_safety),
]

CANONICAL_STAGES = [
    ("dialect_semantics", validate_dialect_semantics),
    ("geometry_preflight", validate_geometry_preflight),
]


def _run_stage_collect(
    subject,
    stages: list[tuple[str, Callable]],
    all_issues: list,
    stages_run: list[str],
) -> tuple[bool, str | None, dict[str, ValidationReport]]:
    """Single-pass: run each validator once, collect reports.

    Returns (ok, failed_stage, reports: dict[stage_name, ValidationReport]).
    """
    reports: dict[str, ValidationReport] = {}

    for stage_name, validator in stages:
        try:
            report = validator(subject)
        except Exception as exc:
            report = ValidationReport.fail(
                stage=stage_name,
                code=f"{stage_name}_validator_exception",
                message=str(exc),
                stages_run=list(stages_run) + [stage_name],
            )

        if not report.stages_run:
            report.stages_run = list(stages_run) + [stage_name]

        reports[stage_name] = report
        all_issues.extend(report.issues)
        stages_run.append(stage_name)

        if not report.ok:
            return False, stage_name, reports

    return True, None, reports


def validate_and_canonicalize_with_bundle(
    raw: dict | RawGcadDocument,
) -> tuple[CanonicalGcadDocument | None, ValidationReport, "ValidationBundle"]:
    """Full pipeline returning structured ValidationBundle. Single-pass validators."""
    from seekflow_engineering_tools.generative_cad.validation.bundle import ValidationBundle

    stages_run: list[str] = []
    all_issues: list = []

    # Parse raw
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
            return None, report, bundle
        raw = parse_result.document

    # ── Raw stages (single pass) ──
    ok, failed_stage, raw_stage_reports = _run_stage_collect(
        raw, RAW_STAGES, all_issues, stages_run,
    )

    if not ok:
        report = ValidationReport(ok=False, stage=failed_stage, issues=all_issues, stages_run=list(stages_run))
        bundle = ValidationBundle(ok=False, raw_stage_reports=raw_stage_reports, canonicalize_report=None, canonical_stage_reports={})
        return None, report, bundle

    # ── Lowering ──
    canonical, c_report = canonicalize(raw)
    all_issues.extend(c_report.issues)
    stages_run.append("canonicalize")
    if not c_report.ok:
        report = ValidationReport(ok=False, stage="canonicalize", issues=all_issues, stages_run=list(stages_run))
        bundle = ValidationBundle(ok=False, raw_stage_reports=raw_stage_reports, canonicalize_report=c_report, canonical_stage_reports={})
        return None, report, bundle

    # ── Canonical stages (single pass) ──
    ok, failed_stage, canonical_stage_reports = _run_stage_collect(
        canonical, CANONICAL_STAGES, all_issues, stages_run,
    )

    if not ok:
        report = ValidationReport(ok=False, stage=failed_stage, issues=all_issues, stages_run=list(stages_run))
        bundle = ValidationBundle(ok=False, raw_stage_reports=raw_stage_reports, canonicalize_report=c_report, canonical_stage_reports=canonical_stage_reports)
        return None, report, bundle

    report = ValidationReport(ok=True, stage="complete", issues=all_issues, stages_run=list(stages_run))
    bundle = ValidationBundle(ok=True, raw_stage_reports=raw_stage_reports, canonicalize_report=c_report, canonical_stage_reports=canonical_stage_reports)
    return canonical, report, bundle


def validate_and_canonicalize(
    raw: dict | RawGcadDocument,
) -> tuple[CanonicalGcadDocument | None, ValidationReport]:
    """Full fail-closed validation pipeline. Backward-compatible wrapper."""
    canonical, report, _bundle = validate_and_canonicalize_with_bundle(raw)
    return canonical, report
