"""Registry validation — dialect existence, op existence, version match."""

from __future__ import annotations

from seekflow_engineering_tools.generative_cad.dialects.registry import require_dialect
from seekflow_engineering_tools.generative_cad.ir.raw import RawGcadDocument
from seekflow_engineering_tools.generative_cad.validation.reports import ValidationReport


def validate_registry(raw: RawGcadDocument) -> ValidationReport:
    issues = []

    for sd in raw.selected_dialects:
        try:
            require_dialect(sd.dialect)
        except KeyError:
            issues.append(ValidationReport.fail(
                "registry", "unknown_dialect",
                f"dialect {sd.dialect!r} is not registered; available: {_available()}",
            ).issues[0])

    # Check node dialects and ops exist
    for node in raw.nodes:
        try:
            dialect = require_dialect(node.dialect)
        except KeyError:
            issues.append(ValidationReport.fail(
                "registry", "unknown_node_dialect",
                f"node {node.id!r} uses unknown dialect {node.dialect!r}",
                node_id=node.id,
            ).issues[0])
            continue

        try:
            # Try to resolve op without version first
            version = node.op_version or dialect.default_op_version(node.op)
            dialect.get_op_spec(node.op, version)
        except (KeyError, ValueError) as exc:
            issues.append(ValidationReport.fail(
                "registry", "unknown_op",
                f"node {node.id!r}: unknown op {node.op!r} in dialect {node.dialect!r}: {exc}",
                node_id=node.id,
            ).issues[0])

    if issues:
        return ValidationReport(ok=False, stage="registry", issues=issues)
    return ValidationReport.ok_report("registry")


def _available() -> list[str]:
    from seekflow_engineering_tools.generative_cad.dialects.registry import list_dialects
    return list_dialects()
