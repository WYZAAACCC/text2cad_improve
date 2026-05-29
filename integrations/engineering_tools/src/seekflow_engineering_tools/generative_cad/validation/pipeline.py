"""Full validation pipeline — RawGcadDocument → CanonicalGcadDocument."""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalGcadDocument
from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
from seekflow_engineering_tools.generative_cad.validation.canonicalize import canonicalize
from seekflow_engineering_tools.generative_cad.validation.graph import validate_graph
from seekflow_engineering_tools.generative_cad.validation.ownership import validate_ownership
from seekflow_engineering_tools.generative_cad.validation.params import validate_params
from seekflow_engineering_tools.generative_cad.validation.phase import validate_phase
from seekflow_engineering_tools.generative_cad.validation.registry import validate_registry
from seekflow_engineering_tools.generative_cad.validation.reports import ValidationReport
from seekflow_engineering_tools.generative_cad.validation.safety import validate_safety
from seekflow_engineering_tools.generative_cad.validation.structure import validate_structure
from seekflow_engineering_tools.generative_cad.validation.typecheck import validate_typecheck


def validate_and_canonicalize(
    raw: dict | RawGcadDocument,
) -> tuple[CanonicalGcadDocument | None, ValidationReport]:
    """Full fail-closed validation pipeline.

    Stages:
    1. structure (component/node uniqueness)
    2. registry (dialect/op existence)
    3. params (operation params model validation)
    4. ownership (component ownership, cross-dialect rules)
    5. graph (DAG, input ref resolution)
    6. typecheck (input/output type matching)
    7. phase (phase order enforcement)
    8. safety (safety flags all true)
    9. canonicalize (build CanonicalGcadDocument)
    """
    if isinstance(raw, dict):
        try:
            raw = RawGcadDocument.model_validate(raw)
        except Exception as exc:
            return None, ValidationReport.fail(
                "structure", "raw_validation_failed",
                f"RawGcadDocument validation failed: {exc}",
            )

    stages = [
        ("structure", validate_structure),
        ("registry", validate_registry),
        ("params", validate_params),
        ("ownership", validate_ownership),
        ("graph", validate_graph),
        ("typecheck", validate_typecheck),
        ("phase", validate_phase),
        ("safety", validate_safety),
    ]

    all_issues = []
    for stage_name, validator in stages:
        report = validator(raw)
        all_issues.extend(report.issues)
        if not report.ok:
            return None, ValidationReport(
                ok=False, stage=stage_name, issues=all_issues,
            )

    # Canonicalize
    canonical, c_report = canonicalize(raw)
    if not c_report.ok:
        all_issues.extend(c_report.issues)
        return None, ValidationReport(
            ok=False, stage="canonicalize", issues=all_issues,
        )

    return canonical, ValidationReport(ok=True, stage="canonicalize", issues=all_issues)
