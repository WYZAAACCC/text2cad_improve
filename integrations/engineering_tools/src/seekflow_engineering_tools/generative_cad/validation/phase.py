"""Phase order validation — topological order must respect phase ordering."""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.dialects.registry import require_dialect
from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
from seekflow_engineering_tools.generative_cad.validation.reports import ValidationReport


def validate_phase(raw: RawGcadDocument) -> ValidationReport:
    issues = []

    # Group nodes by dialect+component for phase checking
    for node in raw.nodes:
        try:
            dialect = require_dialect(node.dialect)
        except KeyError:
            continue
        try:
            version = node.op_version or dialect.default_op_version(node.op)
            op_spec = dialect.get_op_spec(node.op, version)
        except (KeyError, ValueError):
            continue

        if node.phase != op_spec.phase:
            issues.append(ValidationReport.fail(
                "phase", "phase_mismatch",
                f"node {node.id!r} phase {node.phase!r} != op phase {op_spec.phase!r}",
                node_id=node.id,
                expected=op_spec.phase,
                actual=node.phase,
            ).issues[0])

    if issues:
        return ValidationReport(ok=False, stage="phase", issues=issues)
    return ValidationReport.ok_report("phase")
