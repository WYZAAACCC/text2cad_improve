"""Dialect semantic validation — canonical-level, calls dialect.validate_component."""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.dialects.registry import require_dialect
from seekflow_engineering_tools.generative_cad.ir.canonical import CanonicalGcadDocument
from seekflow_engineering_tools.generative_cad.validation.reports import ValidationIssue, ValidationReport


def validate_dialect_semantics(canonical: CanonicalGcadDocument) -> ValidationReport:
    """Run each component's dialect.validate_component on canonical nodes.

    Fail-closed: converts dialect exceptions into ValidationIssue.
    """
    stage = "dialect_semantics"
    issues: list[ValidationIssue] = []

    for component in canonical.components:
        try:
            dialect = require_dialect(component.owner_dialect)
        except KeyError:
            continue  # caught earlier in registry validation

        nodes = [n for n in canonical.nodes if n.component == component.id]

        try:
            report = dialect.validate_component(component, nodes)
        except Exception as exc:
            issues.append(ValidationIssue(
                stage=stage,
                code="dialect_semantic_validator_error",
                message=f"Dialect {component.owner_dialect!r} validator error: {exc}",
                severity="error",
                component_id=component.id,
            ))
            continue

        issues.extend(report.issues)

    return ValidationReport(
        ok=not any(i.severity == "error" for i in issues),
        stage=stage,
        issues=issues,
    )
