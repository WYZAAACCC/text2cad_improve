"""Full validation pipeline — RawGcadDocument → CanonicalGcadDocument.

v0.4: no lazy imports, canonical validators are mandatory, tracks stages_run.
"""

from __future__ import annotations

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


def _run_stages(raw, stages, all_issues, stages_run):
    """Run a list of (stage_name, validator) pairs. Returns (ok, failed_stage)."""
    for stage_name, validator in stages:
        try:
            report = validator(raw)
        except Exception as exc:
            report = ValidationReport.fail(
                stage=stage_name,
                code=f"{stage_name}_validator_exception",
                message=str(exc),
            )
        all_issues.extend(report.issues)
        stages_run.append(stage_name)
        if not report.ok:
            return False, stage_name
    return True, None


def _run_canonical_stages(canonical, stages, all_issues, stages_run):
    """Same as _run_stages but for canonical-level validators."""
    return _run_stages(canonical, stages, all_issues, stages_run)


def validate_and_canonicalize_with_bundle(
    raw: dict | RawGcadDocument,
) -> tuple[CanonicalGcadDocument | None, ValidationReport, "ValidationBundle"]:
    """Full pipeline returning structured ValidationBundle.

    Returns (canonical, combined_report, bundle).
    """
    from seekflow_engineering_tools.generative_cad.validation.bundle import ValidationBundle

    stages_run: list[str] = []
    all_issues: list = []

    # Parse raw
    if isinstance(raw, dict):
        try:
            raw = RawGcadDocument.model_validate(raw)
        except Exception as exc:
            stages_run.append("structure")
            report = ValidationReport.fail(
                "structure", "raw_validation_failed",
                f"RawGcadDocument validation failed: {exc}",
                stages_run=list(stages_run),
            )
            bundle = ValidationBundle(ok=False, raw_stage_reports={}, canonicalize_report=None, canonical_stage_reports={})
            return None, report, bundle

    # ── Raw stages ──
    raw_stage_reports: dict[str, ValidationReport] = {}
    ok, failed_stage = _run_stages(raw, RAW_STAGES, all_issues, stages_run)
    # Reconstruct reports for bundle
    for stage_name, validator in RAW_STAGES:
        try:
            rpt = validator(raw)
        except Exception as exc:
            rpt = ValidationReport.fail(
                stage=stage_name, code=f"{stage_name}_validator_exception", message=str(exc),
            )
        raw_stage_reports[stage_name] = rpt

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

    # ── Canonical stages ──
    canonical_stage_reports: dict[str, ValidationReport] = {}
    ok, failed_stage = _run_canonical_stages(canonical, CANONICAL_STAGES, all_issues, stages_run)
    for stage_name, validator in CANONICAL_STAGES:
        try:
            rpt = validator(canonical)
        except Exception as exc:
            rpt = ValidationReport.fail(
                stage=stage_name, code=f"{stage_name}_validator_exception", message=str(exc),
            )
        canonical_stage_reports[stage_name] = rpt

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
