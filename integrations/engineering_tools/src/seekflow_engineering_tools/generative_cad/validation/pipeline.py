"""Full validation pipeline — RawGcadDocument → CanonicalGcadDocument.

v0.3: adds composition validation, dialect_semantics, and geometry_preflight stages.
"""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalGcadDocument
from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
from seekflow_engineering_tools.generative_cad.validation.canonicalize import canonicalize
from seekflow_engineering_tools.generative_cad.validation.composition import validate_composition_requirements
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

    Raw-level stages:
    1. structure (component/node uniqueness, root_node)
    2. registry (dialect/op existence, version match)
    3. params (operation params model validation)
    4. ownership (component ownership, selected_dialects check)
    5. graph (DAG, input ref resolution)
    6. typecheck (input/output type matching)
    7. phase (phase order enforcement)
    8. composition (multi-component assembly rules)
    9. safety (safety flags all true)

    Lowering:
    10. canonicalize (build CanonicalGcadDocument)

    Canonical-level stages:
    11. dialect_semantics (dialect.validate_component)
    12. geometry_preflight (dialect.preflight_component)
    """
    if isinstance(raw, dict):
        try:
            raw = RawGcadDocument.model_validate(raw)
        except Exception as exc:
            return None, ValidationReport.fail(
                "structure", "raw_validation_failed",
                f"RawGcadDocument validation failed: {exc}",
            )

    # ── Raw-level validations ──
    raw_stages = [
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

    all_issues = []
    for stage_name, validator in raw_stages:
        try:
            report = validator(raw)
        except Exception as exc:
            report = ValidationReport.fail(
                stage=stage_name,
                code=f"{stage_name}_validator_exception",
                message=str(exc),
            )
        all_issues.extend(report.issues)
        if not report.ok:
            return None, ValidationReport(
                ok=False, stage=stage_name, issues=all_issues,
            )

    # ── Lowering: Raw → Canonical ──
    canonical, c_report = canonicalize(raw)
    all_issues.extend(c_report.issues)
    if not c_report.ok:
        return None, ValidationReport(
            ok=False, stage="canonicalize", issues=all_issues,
        )

    # ── Canonical-level validations ──
    canonical_stages = _get_canonical_stages()
    for stage_name, validator in canonical_stages:
        try:
            report = validator(canonical)
        except Exception as exc:
            report = ValidationReport.fail(
                stage=stage_name,
                code=f"{stage_name}_validator_exception",
                message=str(exc),
            )
        all_issues.extend(report.issues)
        if not report.ok:
            return None, ValidationReport(
                ok=False, stage=stage_name, issues=all_issues,
            )

    return canonical, ValidationReport(ok=True, stage="canonicalize", issues=all_issues)


def _get_canonical_stages() -> list:
    """Return canonical-level validation stages. Lazy-imported to allow optional modules."""
    stages = []
    try:
        from seekflow_engineering_tools.generative_cad.validation.dialect_semantics import validate_dialect_semantics
        stages.append(("dialect_semantics", validate_dialect_semantics))
    except ImportError:
        pass
    try:
        from seekflow_engineering_tools.generative_cad.validation.geometry_preflight import validate_geometry_preflight
        stages.append(("geometry_preflight", validate_geometry_preflight))
    except ImportError:
        pass
    return stages
